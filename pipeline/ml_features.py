"""Point-in-time-aware Feature Store builder for the TikTok Shop educational demo.

Reads the existing DuckDB Data Warehouse without changing the model.
Plans that were not known by the as-of cut-off are NOT filled from future Ads.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
import pandas as pd

FEATURE_VERSION = "marketing_aware_v1"
PLAN_REQUIRED = {
    "scenario_id", "product_group_id", "plan_date", "plan_version",
    "planned_ads_spend", "planned_campaign_discount_rate", "recorded_at",
    "plan_source", "plan_status",
}
DAILY_REQUIRED = {
    "event_date", "product_group_id", "net_revenue", "gross_reference_sales",
    "campaign_price_reduction", "ads_cost",
}


class FeatureValidationError(ValueError):
    """Invalid, unavailable or unverifiable feature input."""


def read_warehouse_daily(db_path: str | Path) -> pd.DataFrame:
    """Read existing Date x Product Group Mart: never join Ads to SKU facts."""
    import duckdb
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(f"Data Warehouse missing: {db_path}")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        return con.execute(
            '''SELECT CAST(d."Full_Date" AS DATE) AS event_date,
                      m."Product_Group_ID" AS product_group_id,
                      SUM(m."Net_Revenue") AS net_revenue,
                      SUM(m."Gross_Reference_Sales") AS gross_reference_sales,
                      SUM(m."Campaign_Price_Reduction") AS campaign_price_reduction,
                      SUM(m."Ads_Cost") AS ads_cost
               FROM "Mart_Product_Group_Daily_Performance" m
               JOIN "Dim_Date" d ON d."Date_Key" = m."Date_Key"
               GROUP BY 1, 2 ORDER BY 1, 2'''
        ).df()
    finally:
        con.close()


def _prepare_daily(daily: pd.DataFrame) -> pd.DataFrame:
    missing = DAILY_REQUIRED - set(daily.columns)
    if missing:
        raise FeatureValidationError(f"Daily Mart columns missing: {sorted(missing)}")
    df = daily.copy()
    df["event_date"] = pd.to_datetime(df["event_date"], errors="raise").dt.date
    df["product_group_id"] = df["product_group_id"].astype(str)
    for col in ("net_revenue", "gross_reference_sales", "campaign_price_reduction", "ads_cost"):
        df[col] = pd.to_numeric(df[col], errors="raise")
        if df[col].isna().any():
            raise FeatureValidationError(f"Null financial amount in {col}")
    if df.duplicated(["event_date", "product_group_id"]).any():
        raise FeatureValidationError("Daily Mart not unique at Date x Product Group")
    if (df[["net_revenue", "gross_reference_sales", "campaign_price_reduction", "ads_cost"]] < 0).any().any():
        raise FeatureValidationError("Unexpected negative revenue, campaign, or ads")
    return df


def _prepare_plans(plans: pd.DataFrame) -> pd.DataFrame:
    missing = PLAN_REQUIRED - set(plans.columns)
    if missing:
        raise FeatureValidationError(f"Marketing plan columns missing: {sorted(missing)}")
    p = plans.copy()
    p["product_group_id"] = p["product_group_id"].astype(str)
    p["scenario_id"] = p["scenario_id"].astype(str)
    p["plan_date"] = pd.to_datetime(p["plan_date"], errors="raise").dt.date
    p["recorded_at"] = pd.to_datetime(p["recorded_at"], utc=True, errors="raise")
    p["plan_version"] = pd.to_numeric(p["plan_version"], errors="raise").astype(int)
    for field in ("planned_ads_spend", "planned_campaign_discount_rate"):
        p[field] = pd.to_numeric(p[field], errors="raise")
    if (p["plan_version"] < 1).any():
        raise FeatureValidationError("plan_version must be >= 1")
    if (p["planned_ads_spend"] < 0).any() or p["planned_ads_spend"].isna().any():
        raise FeatureValidationError("planned_ads_spend must be nonnegative")
    discount = p["planned_campaign_discount_rate"]
    if discount.isna().any() or (~discount.between(0, 1)).any():
        raise FeatureValidationError("planned_campaign_discount_rate must be between 0 and 1")
    if p.duplicated(["scenario_id", "product_group_id", "plan_date", "plan_version"]).any():
        raise FeatureValidationError("Duplicate plan versions for Scenario x Group x Day")
    if (~p["plan_status"].isin(["APPROVED", "SCENARIO", "HISTORICAL"])).any():
        raise FeatureValidationError("Invalid or unapproved plan_status")
    if (~p["plan_source"].isin(["USER_SCENARIO", "HISTORICAL_PLAN", "SYNTHETIC_HISTORICAL_PLAN"])).any():
        raise FeatureValidationError("Unknown plan_source")
    return p


def build_feature_rows(
    daily: pd.DataFrame, plans: pd.DataFrame, *, as_of_date: str | date,
    horizon_days: int, scenario_id: str, source_run_id: str,
    feature_version: str = FEATURE_VERSION, min_history_days: int = 28,
    label_available_through: str | date | None = None,
    history_fidelity: str = "RETROSPECTIVE_LATEST_DWH",
) -> pd.DataFrame:
    """Build Group x As-Of x Future Day x Scenario features.

    Historical predictors use only dates <= as_of. Marketing plans must have
    been recorded before end-of-day in Bangkok. Target is separate from X.
    A retrospective current DWH snapshot is NOT point-in-time verified.
    """
    if not 1 <= horizon_days <= 90:
        raise FeatureValidationError("horizon_days must be 1..90")
    if min_history_days < 7:
        raise FeatureValidationError("min_history_days must be >= 7")
    if not scenario_id or not source_run_id or not feature_version:
        raise FeatureValidationError("scenario_id/source_run_id/feature_version required")
    if history_fidelity not in ("RETROSPECTIVE_LATEST_DWH", "POINT_IN_TIME_VERIFIED"):
        raise FeatureValidationError("Invalid history_fidelity")

    cutoff = pd.Timestamp(as_of_date).date()
    cutoff_exclusive = (
        pd.Timestamp(cutoff).tz_localize("Asia/Bangkok") + pd.Timedelta(days=1)
    ).tz_convert("UTC")
    d = _prepare_daily(daily)
    p = _prepare_plans(plans)
    if d.empty:
        raise FeatureValidationError("Daily Mart has no rows")
    if cutoff < d["event_date"].min():
        raise FeatureValidationError("as_of_date precedes warehouse history")
    if cutoff > d["event_date"].max():
        raise FeatureValidationError("as_of_date exceeds latest observed warehouse date")

    # No future Marketing Plans from the current/historical prediction view.
    p = p[(p["scenario_id"] == scenario_id) & (p["recorded_at"] < cutoff_exclusive)]
    p = p.sort_values(["recorded_at", "plan_version"]).drop_duplicates(
        ["scenario_id", "product_group_id", "plan_date"], keep="last"
    )
    selected = {(r.product_group_id, r.plan_date): r for r in p.itertuples(index=False)}
    groups = sorted(d["product_group_id"].unique())
    unknown = sorted(set(p["product_group_id"]) - set(groups))
    if unknown:
        raise FeatureValidationError(f"Unknown Product Group in plans: {unknown}")

    actual_end = d["event_date"].max()
    label_end = (
        pd.Timestamp(label_available_through).date()
        if label_available_through is not None else actual_end
    )
    if label_end > actual_end:
        raise FeatureValidationError("Cannot claim actual labels after latest observed day")
    observed_dates = set(d["event_date"])
    idx = d.set_index(["product_group_id", "event_date"])
    global_start = d["event_date"].min()
    rows = []

    for group in groups:
        # A missing group/day is assumed 0 within the covered date range.
        # This is a DEMO assumption, not a certified data-ingestion watermark.
        group_start = d.loc[d["product_group_id"] == group, "event_date"].min()
        history_start = max(global_start, group_start)

        def daily_value(day: date, col: str) -> float:
            if day < history_start or day > actual_end:
                raise FeatureValidationError(f"Date outside source coverage: {day}")
            try:
                return float(idx.loc[(group, day), col])
            except KeyError:
                return 0.0

        coverage_days = (cutoff - history_start).days + 1
        enough = coverage_days >= min_history_days
        historical = {}
        if enough:
            rev7 = [
                daily_value(cutoff - timedelta(days=i), "net_revenue")
                for i in range(7)
            ]
            rev28 = [
                daily_value(cutoff - timedelta(days=i), "net_revenue")
                for i in range(28)
            ]
            gross = sum(
                daily_value(cutoff - timedelta(days=i), "gross_reference_sales")
                for i in range(7)
            )
            discount = sum(
                daily_value(cutoff - timedelta(days=i), "campaign_price_reduction")
                for i in range(7)
            )
            historical = {
                "revenue_lag_1d": rev7[0],
                "revenue_lag_7d": daily_value(cutoff - timedelta(days=7), "net_revenue"),
                "revenue_avg_7d": sum(rev7) / 7,
                "revenue_avg_28d": sum(rev28) / 28,
                "historical_ads_7d": sum(
                    daily_value(cutoff - timedelta(days=i), "ads_cost")
                    for i in range(7)
                ),
                "historical_discount_7d": discount / gross if gross else None,
            }
        for horizon in range(1, horizon_days + 1):
            forecast_day = cutoff + timedelta(days=horizon)
            plan = selected.get((group, forecast_day))
            status = (
                "INSUFFICIENT_HISTORY" if not enough else
                "MISSING_PLAN" if plan is None else
                "NO_GROSS_SALES" if historical["historical_discount_7d"] is None else
                "READY"
            )
            label = (
                daily_value(forecast_day, "net_revenue")
                if forecast_day <= label_end and forecast_day in observed_dates else None
            )
            source = plan.plan_source if plan is not None else None
            rows.append({
                "feature_version": feature_version,
                "scenario_id": scenario_id,
                "source_run_id": source_run_id,
                "as_of_date": cutoff.isoformat(),
                "forecast_date": forecast_day.isoformat(),
                "product_group_id": group,
                "forecast_horizon": horizon,
                "revenue_lag_1d": historical.get("revenue_lag_1d"),
                "revenue_lag_7d": historical.get("revenue_lag_7d"),
                "revenue_avg_7d": historical.get("revenue_avg_7d"),
                "revenue_avg_28d": historical.get("revenue_avg_28d"),
                "historical_ads_7d": historical.get("historical_ads_7d"),
                "historical_discount_7d": historical.get("historical_discount_7d"),
                "planned_ads_spend": float(plan.planned_ads_spend) if plan is not None else None,
                "planned_campaign_discount_rate": (
                    float(plan.planned_campaign_discount_rate) if plan is not None else None
                ),
                "plan_version": int(plan.plan_version) if plan is not None else None,
                "plan_item_id": getattr(plan, "plan_item_id", None) if plan is not None else None,
                "forecast_weekday": forecast_day.weekday(),
                "target_net_revenue": label,
                "feature_status": status,
                "history_fidelity": history_fidelity,
                "training_ready": bool(
                    status == "READY" and label is not None
                    and history_fidelity == "POINT_IN_TIME_VERIFIED"
                    and source in ("HISTORICAL_PLAN", "SYNTHETIC_HISTORICAL_PLAN")
                ),
                "coverage_note": "MISSING_DATE_ASSUMED_ZERO_WITHIN_OBSERVED_RANGE",
            })
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ML feature snapshot from DuckDB")
    parser.add_argument("--db", required=True)
    parser.add_argument("--plans", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--horizon", type=int, default=7)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--label-through")
    args = parser.parse_args()

    daily = read_warehouse_daily(args.db)
    plans = pd.read_csv(args.plans, dtype={"product_group_id": str, "scenario_id": str})
    features = build_feature_rows(
        daily, plans, as_of_date=args.as_of, horizon_days=args.horizon,
        scenario_id=args.scenario, source_run_id=args.source_run_id,
        label_available_through=args.label_through,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".parquet":
        features.to_parquet(output, index=False)
    elif output.suffix.lower() == ".csv":
        features.to_csv(output, index=False)
    else:
        parser.error("--output must end in .parquet or .csv")
    print(f"Saved {len(features)} rows -> {output}")
    print("Statuses:", features["feature_status"].value_counts().to_dict())
    print("TRAINING NOTE: retrospective DWH is not verified as-of history; training_ready=False")


if __name__ == "__main__":
    main()
