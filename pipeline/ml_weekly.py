"""Weekly Product Group forecasting for an inspectable classroom MLOps demo.

Source: the existing DuckDB Date x Product Group Mart + frozen synthetic
marketing plans. This does not overwrite daily experiments or the DWH.
Predictions are observational, not causal marketing uplift estimates.

Each week: forecast made on the preceding SUNDAY, for MONDAY to SUNDAY.
The forecast and its weekly label have the same Product Group grain.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .generate_ml_history import SCENARIO_ID
from .ml_features import _prepare_daily, _prepare_plans, read_warehouse_daily

MODEL_VERSION = "weekly_sales_lightgbm_demo_v1"
START_WEEK = "2025-12-01"
LAST_WEEK = "2026-09-21"  # historical standalone example only
TEST_WEEKS = 8
VALIDATION_WEEKS = 4
VALIDATION_FOLD_COUNT = 3
MODELS = ("Last Week Naive", "LightGBM History", "LightGBM Marketing")
HISTORY_FEATURES = (
    "product_group_code", "week_of_year", "week_month",
    "revenue_last_week", "revenue_two_weeks_ago",
    "revenue_mean_4weeks", "revenue_std_4weeks",
    "historical_ads_last_week", "historical_discount_last_week",
)
# Fairer ablation: historical features are equal across ML candidates, while
# the marketing-aware candidate also sees KNOWN FUTURE plans.
MARKETING_FEATURES = HISTORY_FEATURES + (
    "planned_ads_week", "planned_discount_mean_week",
    "planned_campaign_days",
)
NUMERIC_INPUTS = MARKETING_FEATURES
GOAL_GROUP_WAPE = 20.0  # demonstration target, not a promise
GOAL_SHOP_WAPE = 15.0


def _d(v):
    return pd.Timestamp(v).date()


def weekly_windows(dataset: pd.DataFrame) -> tuple[list[tuple[str, str, str, str]], str, str, str]:
    """Use only complete observed weeks; keep validation before untouched test."""
    weeks = sorted(dataset.forecast_week_start.unique())
    needed = TEST_WEEKS + VALIDATION_WEEKS * VALIDATION_FOLD_COUNT + 12
    if len(weeks) < needed:
        raise ValueError(f"Need at least {needed} complete weeks for weekly Train/Test")
    test_start = _d(weeks[-TEST_WEEKS])
    test_end = _d(weeks[-1]) + timedelta(days=6)
    folds = []
    first = len(weeks) - TEST_WEEKS - VALIDATION_WEEKS * VALIDATION_FOLD_COUNT
    for i in range(VALIDATION_FOLD_COUNT):
        start = _d(weeks[first + i * VALIDATION_WEEKS])
        end = _d(weeks[first + (i + 1) * VALIDATION_WEEKS - 1]) + timedelta(days=6)
        folds.append((f"Fold {i + 1}", (start - timedelta(days=1)).isoformat(),
                      start.isoformat(), end.isoformat()))
    return folds, (test_start - timedelta(days=1)).isoformat(), test_start.isoformat(), test_end.isoformat()


def _all_days(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]


def build_weekly_dataset(
    daily: pd.DataFrame,
    plans: pd.DataFrame,
    *,
    first_week: str = START_WEEK,
    last_week: str = LAST_WEEK,
    scenario_id: str = SCENARIO_ID,
    source_run_id: str = "synthetic_warehouse_v1",
    skip_incomplete_weeks: bool = False,
) -> pd.DataFrame:
    """Strict full-week materialization; missing days/plans are not filled.

    This is an offline study of CURRENT DWH state. Returning training_ready=True
    or claiming verified historical availability would be incorrect.
    """
    d = _prepare_daily(daily)
    p = _prepare_plans(plans)
    p = p.loc[p.scenario_id == scenario_id].copy()
    if p.empty:
        raise ValueError("No marketing plans for scenario")
    if p["plan_source"].ne("SYNTHETIC_HISTORICAL_PLAN").any():
        raise ValueError("Weekly training requires frozen synthetic historical plans")
    if first_week > last_week:
        raise ValueError("first_week must precede last_week")
    first, last = _d(first_week), _d(last_week)
    if first.weekday() != 0 or last.weekday() != 0:
        raise ValueError("Weekly range must start on MONDAY")

    groups = sorted(d["product_group_id"].unique())
    gcode = {group: i for i, group in enumerate(groups)}
    d = d.set_index(["product_group_id", "event_date"])
    p = p.sort_values(["recorded_at", "plan_version"])
    rows = []
    dates = pd.date_range(first, last, freq="W-MON")
    for week in dates:
        week_rows = []
        week_start = week.date()
        week_end = week_start + timedelta(days=6)
        asof = week_start - timedelta(days=1)
        asof_utc_end_exclusive = (
            pd.Timestamp(week_start).tz_localize("Asia/Bangkok").tz_convert("UTC")
        )
        for group in groups:
            historic_days = _all_days(asof - timedelta(days=27), 28)
            target_days = _all_days(week_start, 7)
            try:
                hist = d.loc[[(group, x) for x in historic_days]]
                target = d.loc[[(group, x) for x in target_days]]
            except KeyError as exc:
                if skip_incomplete_weeks:
                    break
                raise ValueError(
                    f"Incomplete daily DWH coverage: {group} week {week_start}"
                ) from exc
            if len(hist) != 28 or len(target) != 7:
                if skip_incomplete_weeks:
                    break
                raise ValueError("Daily coverage must contain each exact day")
            window_plans = p.loc[
                p["product_group_id"].eq(group) &
                p["plan_date"].isin(target_days) &
                p["recorded_at"].lt(asof_utc_end_exclusive)
            ].drop_duplicates(["plan_date"], keep="last")
            if len(window_plans) != 7:
                if skip_incomplete_weeks:
                    break
                raise ValueError(
                    f"Missing pre-approved historical plans: {group} week {week_start}"
                )
            # History is chronologically ordered by explicit requested indices.
            rev = hist.net_revenue.to_numpy(dtype=float)
            ads = hist.ads_cost.to_numpy(dtype=float)
            gross = hist.gross_reference_sales.to_numpy(dtype=float)
            camp = hist.campaign_price_reduction.to_numpy(dtype=float)
            last4 = [float(rev[j:j+7].sum()) for j in (0, 7, 14, 21)]
            prev7_gross = float(gross[-7:].sum())
            previous_campaign_ratio = (
                float(camp[-7:].sum() / prev7_gross)
                if prev7_gross > 0 else 0.0
            )
            week_rows.append({
                "scenario_id": scenario_id,
                "source_run_id": source_run_id,
                "feature_version": MODEL_VERSION,
                "as_of_date": asof.isoformat(),
                "forecast_week_start": week_start.isoformat(),
                "forecast_week_end": week_end.isoformat(),
                "product_group_id": group,
                "product_group_code": gcode[group],
                "week_of_year": week_start.isocalendar().week,
                "week_month": week_start.month,
                "revenue_last_week": last4[3],
                "revenue_two_weeks_ago": last4[2],
                "revenue_mean_4weeks": float(np.mean(last4)),
                "revenue_std_4weeks": float(np.std(last4)),
                "historical_ads_last_week": float(ads[-7:].sum()),
                "historical_discount_last_week": previous_campaign_ratio,
                "planned_ads_week": float(window_plans.planned_ads_spend.sum()),
                "planned_discount_mean_week": float(window_plans.planned_campaign_discount_rate.mean()),
                "planned_campaign_days": int(window_plans.planned_campaign_discount_rate.gt(0).sum()),
                "actual_net_revenue_week": float(target.net_revenue.sum()),
                "history_fidelity": "RETROSPECTIVE_LATEST_DWH",
                "training_ready": False,
            })
        if len(week_rows) == len(groups):
            rows.extend(week_rows)
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("No training weeks")
    if result.duplicated(["scenario_id", "product_group_id", "forecast_week_start"]).any():
        raise AssertionError("Duplicate week x Product Group")
    if result[list(NUMERIC_INPUTS) + ["actual_net_revenue_week"]].isnull().any().any():
        raise AssertionError("Missing ML features or labels")
    if result[list(NUMERIC_INPUTS) + ["actual_net_revenue_week"]].lt(0).any().any():
        raise AssertionError("Negative weekly data")
    if result.training_ready.any():
        raise AssertionError("Retrospective data cannot be auto-PIT-approved")
    return result


def split_weekly(
    dataset: pd.DataFrame, *,
    train_end: str, valid_start: str, valid_end: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Target WEEK is the grouping key; never split the same week across sets."""
    if not (train_end < valid_start <= valid_end):
        raise ValueError("Invalid chronological training and validation windows")
    tr = dataset.loc[dataset.forecast_week_end.le(train_end)].copy()
    val = dataset.loc[
        dataset.forecast_week_start.ge(valid_start) &
        dataset.forecast_week_end.le(valid_end)
    ].copy()
    if tr.empty or val.empty:
        raise ValueError("Empty weekly train or test group")
    assert set(tr.forecast_week_start).isdisjoint(val.forecast_week_start)
    assert max(tr.forecast_week_end) < min(val.forecast_week_start)
    return tr, val


def _score(actual, prediction):
    y = np.asarray(actual, dtype=float)
    yhat = np.asarray(prediction, dtype=float)
    if not len(y) or len(y) != len(yhat) or not np.isfinite(y).all() or not np.isfinite(yhat).all():
        raise ValueError("Invalid weekly metrics inputs")
    err = yhat - y
    denominator = float(np.abs(y).sum())
    return {
        "samples": int(len(y)),
        "mae_thb_per_week": round(float(np.abs(err).mean()), 2),
        "wape_pct": round(float(100 * np.abs(err).sum() / denominator), 3) if denominator else None,
        "bias_pct": round(float(100 * err.sum() / denominator), 3) if denominator else None,
        "actual_revenue_thb": round(float(y.sum()), 2),
        "predicted_revenue_thb": round(float(yhat.sum()), 2),
        "absolute_error_sum_thb": round(float(np.abs(err).sum()), 2),
    }


def _fit(which, train):
    if which == "Last Week Naive":
        return None
    try:
        import lightgbm as lgb
    except ImportError as exc:
        raise RuntimeError("Install python -m pip install -r requirements-ml.txt") from exc
    cols = HISTORY_FEATURES if which == "LightGBM History" else MARKETING_FEATURES
    model = lgb.LGBMRegressor(
        objective="regression", random_state=8102, n_jobs=2,
        n_estimators=200, learning_rate=0.035, max_depth=4, num_leaves=10,
        min_child_samples=9, reg_lambda=2.0, verbosity=-1,
    )
    model.fit(train[list(cols)], train.actual_net_revenue_week)
    return model


def _predict(which, model, frame):
    if which == "Last Week Naive":
        pred = frame.revenue_last_week.to_numpy(dtype=float)
    else:
        cols = HISTORY_FEATURES if which == "LightGBM History" else MARKETING_FEATURES
        pred = model.predict(frame[list(cols)])
    return np.maximum(np.asarray(pred, dtype=float), 0)


def _score_shop_grouped(prediction_frame: pd.DataFrame):
    shop = prediction_frame.groupby("forecast_week_start", as_index=False)[
        ["actual_net_revenue_week", "predicted_net_revenue_week"]
    ].sum()
    return _score(shop.actual_net_revenue_week, shop.predicted_net_revenue_week)


def train_evaluate_weekly(dataset: pd.DataFrame, destination: str | Path) -> dict:
    """Choose model from validation, *then* inspect an untouched weekly test."""
    folder = Path(destination)
    folder.mkdir(parents=True, exist_ok=True)
    validation_folds, train_end, test_start, test_end = weekly_windows(dataset)
    fold_rows, fold_predictions = [], []
    for fold_name, train_thru, start, end in validation_folds:
        tr, val = split_weekly(dataset, train_end=train_thru,
                               valid_start=start, valid_end=end)
        for name in MODELS:
            model = _fit(name, tr)
            pred = _predict(name, model, val)
            data = val[["forecast_week_start", "product_group_id", "actual_net_revenue_week"]].copy()
            data["predicted_net_revenue_week"] = pred
            data["model"] = name
            data["fold"] = fold_name
            fold_predictions.append(data)
            group_score = _score(data.actual_net_revenue_week, pred)
            shop_score = _score_shop_grouped(data)
            fold_rows.append({
                "fold": fold_name, "model": name,
                "train_rows": len(tr), "validation_rows": len(val),
                "group_wape_pct": group_score["wape_pct"],
                "shop_wape_pct": shop_score["wape_pct"],
                "group_mae_thb_week": group_score["mae_thb_per_week"],
                "absolute_error_sum_thb": group_score["absolute_error_sum_thb"],
                "actual_revenue_thb": group_score["actual_revenue_thb"],
            })
    fold_df = pd.DataFrame(fold_rows)
    fold_df.to_csv(folder / "weekly_rolling_folds.csv", index=False)
    pd.concat(fold_predictions).to_csv(folder / "weekly_validation_predictions.csv", index=False)

    selection = []
    for model_name in MODELS:
        sub = fold_df.loc[fold_df.model.eq(model_name)]
        selection.append({
            "model": model_name,
            "validation_group_wape_pct": round(
                100 * sub.absolute_error_sum_thb.sum() / sub.actual_revenue_thb.sum(), 3
            ),
            "folds": int(len(sub)),
        })
    selection_df = pd.DataFrame(selection).sort_values(
        ["validation_group_wape_pct", "model"]
    )
    selection_df.to_csv(folder / "weekly_model_selection.csv", index=False)
    selected_model = str(selection_df.iloc[0]["model"])

    tr, test = split_weekly(
        dataset, train_end=train_end,
        valid_start=test_start, valid_end=test_end,
    )
    test_results = []
    per_group = []
    test_predictions = []
    trained_models = {}
    for name in MODELS:
        model = _fit(name, tr)
        if model is not None:
            trained_models[name] = model
            model_file = (
                "weekly_history_model.txt" if name == "LightGBM History"
                else "weekly_marketing_model.txt"
            )
            model.booster_.save_model(str(folder / model_file))
        yhat = _predict(name, model, test)
        data = test[[
            "as_of_date", "forecast_week_start", "forecast_week_end",
            "product_group_id", "actual_net_revenue_week",
            "history_fidelity",
        ]].copy()
        data["predicted_net_revenue_week"] = yhat
        data["model"] = name
        data["error_thb"] = data.predicted_net_revenue_week - data.actual_net_revenue_week
        test_predictions.append(data)
        group_score = _score(data.actual_net_revenue_week, yhat)
        shop_score = _score_shop_grouped(data)
        test_results.append({
            "model": name,
            "group_wape_pct": group_score["wape_pct"],
            "shop_wape_pct": shop_score["wape_pct"],
            "group_mae_thb_per_week": group_score["mae_thb_per_week"],
            "shop_mae_thb_per_week": shop_score["mae_thb_per_week"],
            "group_bias_pct": group_score["bias_pct"],
            "shop_bias_pct": shop_score["bias_pct"],
            "test_group_weeks": group_score["samples"],
            "test_shop_weeks": shop_score["samples"],
            "group_target_20pct": bool(group_score["wape_pct"] <= GOAL_GROUP_WAPE),
            "shop_target_15pct": bool(shop_score["wape_pct"] <= GOAL_SHOP_WAPE),
        })
        for group, subset in data.groupby("product_group_id"):
            per_group.append({
                "model": name, "product_group_id": group,
                **_score(subset.actual_net_revenue_week, subset.predicted_net_revenue_week),
            })

    all_preds = pd.concat(test_predictions, ignore_index=True)
    all_preds.to_csv(folder / "weekly_test_predictions.csv", index=False)
    pd.DataFrame(test_results).to_csv(folder / "weekly_test_metrics.csv", index=False)
    pd.DataFrame(per_group).to_csv(folder / "weekly_test_by_group.csv", index=False)

    # Deployment simulation uses saved MODEL and stored features, never a
    # prewritten fake prediction. Actual prediction is checked in a serving test.
    model_index = {
        "model_version": MODEL_VERSION,
        "selected_model": selected_model,
        "models_available": list(trained_models),
        "group_encoding": {
            g: int(code)
            for g, code in dataset[["product_group_id", "product_group_code"]].drop_duplicates().values
        },
        "train_cutoff_week_end": train_end,
        "test_window": [test_start, test_end],
        "feature_columns": list(
            HISTORY_FEATURES if selected_model == "LightGBM History"
            else MARKETING_FEATURES if selected_model == "LightGBM Marketing"
            else ("revenue_last_week",)
        ),
        "history_fidelity": "RETROSPECTIVE_LATEST_DWH",
        "selected_by": "rolling_validation_group_wape",
        "model_approval": "DEMO_ONLY",
    }
    (folder / "weekly_model_registry.json").write_text(
        json.dumps(model_index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    marketing_importance = trained_models["LightGBM Marketing"].booster_.feature_importance(
        importance_type="gain"
    )
    pd.DataFrame({
        "feature": MARKETING_FEATURES, "gain": marketing_importance
    }).sort_values("gain", ascending=False).to_csv(
        folder / "weekly_feature_importance.csv", index=False
    )

    dataset.to_parquet(folder / "weekly_training_dataset.parquet", index=False)
    feature_hash = hashlib.sha256(
        dataset[["forecast_week_start", "product_group_id", "actual_net_revenue_week"]]
        .to_csv(index=False).encode("utf-8")
    ).hexdigest()
    summary = {
        "model_version": MODEL_VERSION,
        "data": "SYNTHETIC_EDUCATIONAL_NOT_TIKTOK",
        "fidelity": "RETROSPECTIVE_LATEST_DWH",
        "model_use": "DEMO_ONLY_NOT_PRODUCTION",
        "dataset_rows": len(dataset),
        "weeks": dataset.forecast_week_start.nunique(),
        "groups": dataset.product_group_id.nunique(),
        "dataset_hash_sha256": feature_hash,
        "weekly_grain": "Monday-Sunday x Product Group",
        "forecast_asof": "Previous Sunday",
        "validation_folds": [x[0] for x in validation_folds],
        "validation_windows": [{"fold": name, "train_through": thru,
                                "from": start, "through": end}
                               for name, thru, start, end in validation_folds],
        "train_cutoff_week_end": train_end,
        "selected_by_validation": selected_model,
        "validation_model_comparison": selection,
        "final_test_window": [test_start, test_end],
        "final_test_comparison": test_results,
        "targets": {"group_wape_pct": GOAL_GROUP_WAPE, "shop_wape_pct": GOAL_SHOP_WAPE},
        "test_not_used_for_model_selection": True,
        "limits": [
            "Plans have synthetic recorded-at timestamps; not evidence of actual decisions",
            "Current warehouse snapshots may contain retrospective backfilled updates",
            "Models learn association, not incremental causal effect of Ads/Discount",
            "Do not set, overwrite or fake WAPE. Scores are computed from actual holdout",
        ],
    }
    (folder / "weekly_backtest_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def run_weekly(warehouse: str | Path, plans: str | Path, output: str | Path):
    daily = read_warehouse_daily(warehouse)
    plan_df = pd.read_csv(plans, dtype={"product_group_id": str, "scenario_id": str})
    latest = min(pd.Timestamp(daily.event_date.max()).date(),
                 pd.to_datetime(plan_df.plan_date).dt.date.max())
    last_sunday = latest - timedelta(days=(latest.weekday() + 1) % 7)
    last_week = last_sunday - timedelta(days=6)
    dataset = build_weekly_dataset(daily, plan_df, last_week=last_week.isoformat(),
                                   skip_incomplete_weeks=True)
    return train_evaluate_weekly(dataset, output)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Weekly Marketing-Aware MLOps demo")
    parser.add_argument("--warehouse", required=True)
    parser.add_argument("--plans", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(run_weekly(args.warehouse, args.plans, args.output),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
