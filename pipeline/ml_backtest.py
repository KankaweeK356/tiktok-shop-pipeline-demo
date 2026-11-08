"""Offline ML lab: feature snapshots, rolling time backtests, honest model comparison.

Synthetic educational data only. Not a causal Ads/discount optimization model.
Training examples are RETROSPECTIVE_LATEST_DWH and are never promoted as PIT verified.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .generate_ml_history import SCENARIO_ID
from .ml_features import build_feature_rows, read_warehouse_daily

ML_VERSION = "marketing_aware_lightgbm_v1"
HORIZON_DAYS = 7
AS_OF_START = "2025-11-28"
AS_OF_END = "2026-09-23"
FINAL_TEST_START = "2026-08-01"
FINAL_TEST_END = "2026-09-30"
TRAINVAL_END = "2026-07-31"

# Last observed target date in each training fold / following validation period.
ROLLING_FOLDS = (
    ("F1", "2026-04-30", "2026-05-01", "2026-05-31"),
    ("F2", "2026-05-31", "2026-06-01", "2026-06-30"),
    ("F3", "2026-06-30", "2026-07-01", "2026-07-31"),
)

BASE_FEATURES = (
    "product_group_code", "forecast_weekday", "forecast_month",
    "forecast_horizon", "revenue_lag_1d", "revenue_lag_7d",
    "revenue_avg_7d", "revenue_avg_28d",
)
MARKETING_FEATURES = BASE_FEATURES + (
    "historical_ads_7d", "historical_discount_7d",
    "planned_ads_spend", "planned_campaign_discount_rate",
)
EXPERIMENTS = ("Seasonal Naive", "LightGBM Historical", "LightGBM Marketing-Aware")


def _date(x) -> date:
    return pd.Timestamp(x).date()


def build_training_dataset(
    daily: pd.DataFrame,
    plans: pd.DataFrame,
    *,
    as_of_start: str = AS_OF_START,
    as_of_end: str = AS_OF_END,
    target_last_day: str = FINAL_TEST_END,
    horizon: int = HORIZON_DAYS,
    scenario_id: str = SCENARIO_ID,
    source_run_id: str = "ml-history-run",
) -> pd.DataFrame:
    """Materialize future-date labels and only observed historical predictors.

    Training example grain: (as_of_date, forecast_date, Product Group, scenario).
    A target date appears for several as-of dates: keep them separate by horizon.
    Date x Group sales are read from DWH once. The builder is shared with inference.
    """
    if not 1 <= horizon <= 7:
        raise ValueError("Offline Seasonal Naive baseline requires horizon 1..7")
    first, last = _date(as_of_start), _date(as_of_end)
    target_last = _date(target_last_day)
    if first > last or last >= target_last:
        raise ValueError("Invalid as-of and target date bounds")
    clean = daily.copy()
    clean["event_date"] = pd.to_datetime(clean["event_date"]).dt.date
    if clean.duplicated(["event_date", "product_group_id"]).any():
        raise ValueError("DWH Date x Group uniqueness violated")
    baseline_lookup = {
        (str(r.product_group_id), r.event_date): float(r.net_revenue)
        for r in clean.itertuples(index=False)
    }
    group_codes = {v: i for i, v in enumerate(sorted(clean["product_group_id"].unique()))}
    parts = []
    for asof in pd.date_range(first, last):
        rows = build_feature_rows(
            daily, plans,
            as_of_date=asof.date(), horizon_days=horizon,
            scenario_id=scenario_id, source_run_id=source_run_id,
            label_available_through=target_last,
        )
        rows = rows.loc[
            rows["feature_status"].eq("READY") &
            rows["target_net_revenue"].notna()
        ].copy()
        if rows.empty:
            continue
        rows["product_group_code"] = rows["product_group_id"].map(group_codes).astype("int16")
        rows["forecast_month"] = pd.to_datetime(rows["forecast_date"]).dt.month.astype("int16")
        # 7-day same-weekday value is available at each as-of date for h<=7.
        rows["seasonal_naive_prediction"] = [
            baseline_lookup.get((str(group), _date(forecast) - timedelta(days=7)), 0.0)
            for group, forecast in zip(rows["product_group_id"], rows["forecast_date"])
        ]
        parts.append(rows)
    if not parts:
        raise ValueError("No valid training snapshots. Check history/marketing-plan coverage.")
    out = pd.concat(parts, ignore_index=True)
    keys = ["scenario_id", "product_group_id", "as_of_date", "forecast_date"]
    if out.duplicated(keys).any():
        raise AssertionError("ML feature grain is not unique")
    if (pd.to_datetime(out["forecast_date"]) <= pd.to_datetime(out["as_of_date"])).any():
        raise AssertionError("Target not after feature as-of date")
    if (out["target_net_revenue"] < 0).any():
        raise AssertionError("Negative daily Net Revenue is outside demo scope")
    if out["training_ready"].any():
        raise AssertionError("Retrospective snapshots must not claim PIT verification")
    if set(out["history_fidelity"]) != {"RETROSPECTIVE_LATEST_DWH"}:
        raise AssertionError("Unexpected history fidelity upgrade")
    for col in MARKETING_FEATURES + ("seasonal_naive_prediction", "target_net_revenue"):
        if out[col].isna().any():
            raise AssertionError(f"Null in selected ML feature/label: {col}")
    return out


def _frame_with_dates(dataset: pd.DataFrame) -> pd.DataFrame:
    frame = dataset.copy()
    frame["target_date"] = pd.to_datetime(frame["forecast_date"])
    frame["asof_ts"] = pd.to_datetime(frame["as_of_date"])
    return frame


def split_by_target(
    dataset: pd.DataFrame, *,
    train_through: str,
    validation_from: str,
    validation_through: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Group all horizons for the SAME target date into one temporal split."""
    data = _frame_with_dates(dataset)
    train_end = pd.Timestamp(train_through)
    val_start = pd.Timestamp(validation_from)
    val_end = pd.Timestamp(validation_through)
    if not train_end < val_start <= val_end:
        raise ValueError("Split dates must be ordered")
    train = data.loc[data["target_date"] <= train_end].copy()
    valid = data.loc[
        data["target_date"].between(val_start, val_end, inclusive="both")
    ].copy()
    if train.empty or valid.empty:
        raise ValueError("Train/validation split is empty")
    if set(train["forecast_date"]) & set(valid["forecast_date"]):
        raise AssertionError("Target date leakage across split")
    if train["target_date"].max() >= valid["target_date"].min():
        raise AssertionError("Temporal leakage across target cutoff")
    return train, valid


def _metrics(actual, forecast) -> dict:
    actual = np.asarray(actual, dtype=float)
    forecast = np.asarray(forecast, dtype=float)
    if len(actual) != len(forecast) or len(actual) == 0:
        raise ValueError("Cannot evaluate empty or misaligned predictions")
    if not np.isfinite(actual).all() or not np.isfinite(forecast).all():
        raise ValueError("Metrics require finite actual/predictions")
    errors = forecast - actual
    denom = float(np.abs(actual).sum())
    return {
        "samples": len(actual),
        "mae_thb": round(float(np.abs(errors).mean()), 3),
        "wape_pct": round(float(np.abs(errors).sum() / denom * 100), 3) if denom > 0 else None,
        "bias_pct": round(float(errors.sum() / denom * 100), 3) if denom > 0 else None,
        "actual_sum": round(float(actual.sum()), 2),
        "predicted_sum": round(float(forecast.sum()), 2),
    }


def _model(columns: tuple[str, ...]):
    try:
        import lightgbm as lgb
    except ImportError as e:
        raise RuntimeError("Install ML extras: pip install -r requirements-ml.txt") from e
    # Small conservative tree and fixed seed; hyperparameters not tuned on test.
    return lgb.LGBMRegressor(
        objective="regression", n_estimators=150, learning_rate=0.05,
        num_leaves=15, max_depth=5, min_child_samples=35,
        colsample_bytree=1.0, subsample=1.0, reg_lambda=2.0,
        random_state=8102, n_jobs=2, verbosity=-1,
    )


def _predict_for_candidate(name: str, model, data: pd.DataFrame) -> np.ndarray:
    if name == "Seasonal Naive":
        result = data["seasonal_naive_prediction"].to_numpy(dtype=float)
    else:
        cols = BASE_FEATURES if name == "LightGBM Historical" else MARKETING_FEATURES
        result = model.predict(data[list(cols)])
    return np.maximum(np.asarray(result, dtype=float), 0)


def backtest_models(dataset: pd.DataFrame, output_dir: str | Path) -> dict:
    """Walk-forward validation, then refit before a locked final test (Aug-Sep).

    Validation fold selection, NOT final test, selects the model. All models
    are reported on final test to prevent cherry-picking just the winner.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    folds = []
    fold_rows = []
    for fold_id, train_end, valid_start, valid_end in ROLLING_FOLDS:
        train, valid = split_by_target(
            dataset, train_through=train_end,
            validation_from=valid_start, validation_through=valid_end,
        )
        predictions = {}
        for model_name in EXPERIMENTS:
            fitted = None
            if model_name != "Seasonal Naive":
                columns = BASE_FEATURES if model_name == "LightGBM Historical" else MARKETING_FEATURES
                fitted = _model(columns)
                fitted.fit(train[list(columns)], train["target_net_revenue"])
            pred = _predict_for_candidate(model_name, fitted, valid)
            score = _metrics(valid["target_net_revenue"], pred)
            fold_rows.append({
                "fold": fold_id, "train_through": train_end,
                "validation_from": valid_start, "validation_through": valid_end,
                "model": model_name, **score,
            })
            predictions[model_name] = pred
        folds.append({
            "fold": fold_id, "train_rows": len(train),
            "validation_rows": len(valid),
            "first_validation_date": str(valid["forecast_date"].min()),
            "last_validation_date": str(valid["forecast_date"].max()),
        })
    folds_df = pd.DataFrame(fold_rows)
    folds_df.to_csv(output / "fold_validation_metrics.csv", index=False)

    # Aggregate errors using denominators, not the arithmetic mean of WAPE.
    selection = []
    for model_name in EXPERIMENTS:
        sub = folds_df.loc[folds_df["model"] == model_name]
        # Fold WAPE weighted by actual turnover (each sample appears once/fold).
        numer = (sub["wape_pct"] / 100.0 * sub["actual_sum"]).sum()
        denom = sub["actual_sum"].sum()
        selection.append({
            "model": model_name,
            "validation_weighted_wape_pct": round(float(numer / denom * 100), 3),
            "folds_evaluated": len(sub),
        })
    selection_df = pd.DataFrame(selection).sort_values(
        ["validation_weighted_wape_pct", "model"]
    )
    selected = str(selection_df.iloc[0]["model"])
    selection_df.to_csv(output / "model_selection_metrics.csv", index=False)

    # Locked last two months: train everything with label <= 31 July.
    final_train, final_test = split_by_target(
        dataset, train_through=TRAINVAL_END,
        validation_from=FINAL_TEST_START, validation_through=FINAL_TEST_END,
    )
    models = {}
    final_predictions = []
    test_overall = []
    test_group = []
    test_horizon = []
    for model_name in EXPERIMENTS:
        fitted = None
        if model_name != "Seasonal Naive":
            columns = BASE_FEATURES if model_name == "LightGBM Historical" else MARKETING_FEATURES
            fitted = _model(columns)
            fitted.fit(final_train[list(columns)], final_train["target_net_revenue"])
            models[model_name] = fitted
            path = output / (
                "model_history.txt" if model_name == "LightGBM Historical"
                else "model_marketing.txt"
            )
            fitted.booster_.save_model(str(path))
        pred = _predict_for_candidate(model_name, fitted, final_test)
        results = final_test[[
            "as_of_date", "forecast_date", "forecast_horizon",
            "product_group_id", "scenario_id", "target_net_revenue",
            "history_fidelity",
        ]].copy()
        results["model"] = model_name
        results["predicted_net_revenue"] = pred
        results["error_thb"] = results["predicted_net_revenue"] - results["target_net_revenue"]
        final_predictions.append(results)
        test_overall.append({"model": model_name, **_metrics(results["target_net_revenue"], pred)})
        for group, part in results.groupby("product_group_id", sort=True):
            test_group.append({"model": model_name, "product_group_id": group,
                               **_metrics(part["target_net_revenue"], part["predicted_net_revenue"])})
        for horizon, part in results.groupby("forecast_horizon", sort=True):
            test_horizon.append({"model": model_name, "forecast_horizon": int(horizon),
                                 **_metrics(part["target_net_revenue"], part["predicted_net_revenue"])})

    pd.concat(final_predictions, ignore_index=True).to_csv(
        output / "test_predictions.csv", index=False)
    pd.DataFrame(test_overall).to_csv(output / "test_overall_metrics.csv", index=False)
    pd.DataFrame(test_group).to_csv(output / "test_group_metrics.csv", index=False)
    pd.DataFrame(test_horizon).to_csv(output / "test_horizon_metrics.csv", index=False)

    importance = models["LightGBM Marketing-Aware"].booster_.feature_importance(
        importance_type="gain"
    )
    pd.DataFrame({
        "feature": MARKETING_FEATURES,
        "gain": importance,
    }).sort_values("gain", ascending=False).to_csv(
        output / "marketing_feature_importance.csv", index=False
    )

    dataset.to_parquet(output / "offline_feature_dataset.parquet", index=False)
    feature_sha = hashlib.sha256(
        dataset[[
            "as_of_date", "forecast_date", "product_group_id",
            "target_net_revenue", "planned_ads_spend",
            "planned_campaign_discount_rate",
        ]].to_csv(index=False).encode("utf-8")
    ).hexdigest()
    chosen_score = next(s for s in test_overall if s["model"] == selected)
    summary = {
        "experiment_version": ML_VERSION,
        "data_classification": "SYNTHETIC_EDUCATIONAL_NOT_TIKTOK",
        "model_use": "RESEARCH_ONLY_NOT_PRODUCTION_APPROVED",
        "feature_history_fidelity": "RETROSPECTIVE_LATEST_DWH",
        "ml_target": "Daily Net Revenue by Product Group",
        "forecast_horizon_days": HORIZON_DAYS,
        "train_validation_through": TRAINVAL_END,
        "final_test_from": FINAL_TEST_START,
        "final_test_through": FINAL_TEST_END,
        "selected_by": "rolling_fold_validation_wape_not_test",
        "selected_model": selected,
        "selected_model_final_test": chosen_score,
        "full_test_comparison": test_overall,
        "rolling_validation_folds": folds,
        "eligible_snapshots": int(len(dataset)),
        "feature_sha256": feature_sha,
        "selected_historical_plan_features": [
            "planned_ads_spend", "planned_campaign_discount_rate"
        ],
        "caveats": [
            "Synthetic Ads/discount correlations do not establish causal effects",
            "Retrospective DWH includes future corrections; point-in-time snapshots not verified",
            "Forecasts are rolling daily as-of predictions, not one static 60-day forecast",
            "Offline training_ready remains false; never describe model as production validated",
            "No model can infer demand uplift reliably from unsupported new scenarios",
        ],
    }
    (output / "backtest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def run_backtesting(
    warehouse_path: str | Path, plans_path: str | Path, output_dir: str | Path,
    *, source_run_id: str = "mlhistory-initial-incremental",
) -> dict:
    daily = read_warehouse_daily(warehouse_path)
    plans = pd.read_csv(plans_path, dtype={"product_group_id": str, "scenario_id": str})
    dataset = build_training_dataset(
        daily, plans, source_run_id=source_run_id,
    )
    return backtest_models(dataset, output_dir)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Time-series CV for Synthetic TikTok ML Lab")
    parser.add_argument("--warehouse", required=True)
    parser.add_argument("--plans", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run_backtesting(args.warehouse, args.plans, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
