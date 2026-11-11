"""Batch serving and monitoring REPLAY of a held-out week.

For classroom MLOps level-1 workflow only. It re-loads the model artifact and
constructs predictions from features, rather than showing hard-coded scores.
The held-out label is accessed only AFTER prediction, for monitoring.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .ml_weekly import (
    _score, _score_shop_grouped, MODEL_VERSION,
    MARKETING_FEATURES, HISTORY_FEATURES,
)


def serve_monitor_replay(
    output_dir: str | Path, *, forecast_week: str | None = None,
) -> dict:
    output = Path(output_dir)
    registry = json.loads((output / "weekly_model_registry.json").read_text(encoding="utf-8"))
    if registry["model_version"] != MODEL_VERSION:
        raise ValueError("Model registry version mismatch")
    if registry["model_approval"] != "DEMO_ONLY":
        raise ValueError("Unexpected model approval status")
    test_start, test_end = registry["test_window"]
    if forecast_week is None:
        forecast_week = (pd.Timestamp(test_end) - pd.Timedelta(days=6)).date().isoformat()
    # For an honest replay, do not include labels in model features.
    dataset = pd.read_parquet(output / "weekly_training_dataset.parquet")
    group_rows = dataset.loc[dataset.forecast_week_start.eq(forecast_week)].copy()
    groups = set(registry["group_encoding"])
    if group_rows.empty or set(group_rows.product_group_id) != groups:
        raise ValueError("Missing complete week and groups for serving replay")
    if group_rows.training_ready.any():
        raise AssertionError("Unverified PIT features must not be marked training_ready")
    if forecast_week < test_start or group_rows.forecast_week_end.max() > test_end:
        raise ValueError("Only archived hold-out replay dates are supported")
    if not (group_rows.as_of_date < group_rows.forecast_week_start).all():
        raise AssertionError("Serving input contains unavailable dates")

    selected = registry["selected_model"]
    cols = registry["feature_columns"]
    if selected == "Last Week Naive":
        predicted = group_rows.revenue_last_week.to_numpy(dtype=float)
        file_used = "seasonal-naive-rule"
    else:
        try:
            import lightgbm as lgb
        except ImportError as exc:
            raise RuntimeError("Install requirements-ml.txt") from exc
        fname = (
            "weekly_history_model.txt" if selected == "LightGBM History"
            else "weekly_marketing_model.txt"
        )
        file_used = str(output / fname)
        fitted = lgb.Booster(model_file=file_used)
        expected = HISTORY_FEATURES if selected == "LightGBM History" else MARKETING_FEATURES
        if tuple(cols) != tuple(expected):
            raise AssertionError("Serving feature order differs from training")
        predicted = fitted.predict(group_rows[cols])
    predicted = np.maximum(np.asarray(predicted, dtype=float), 0)

    response = group_rows[[
        "as_of_date", "forecast_week_start", "forecast_week_end",
        "product_group_id", "source_run_id", "history_fidelity",
    ]].copy()
    response["selected_model"] = selected
    response["model_version"] = registry["model_version"]
    response["predicted_net_revenue_week"] = predicted
    response.to_csv(output / "serving_replay_predictions.csv", index=False)

    # In an online service, monitoring occurs once actual labels arrive later.
    # Here labels exist ONLY because the fixed week is a historical holdout.
    labels = group_rows.actual_net_revenue_week
    group = _score(labels, predicted)
    compare = pd.DataFrame({
        "forecast_week_start": group_rows.forecast_week_start,
        "actual_net_revenue_week": labels,
        "predicted_net_revenue_week": predicted,
    })
    shop = _score_shop_grouped(compare)
    alerts = []
    if group["wape_pct"] is not None and group["wape_pct"] > 20:
        alerts.append("GROUP_WAPE_EXCEEDS_DEMO_TARGET_20PCT")
    if shop["wape_pct"] is not None and shop["wape_pct"] > 15:
        alerts.append("SHOP_WAPE_EXCEEDS_DEMO_TARGET_15PCT")
    monitor = {
        "status": "MONITORED",
        "monitoring_mode": "OFFLINE_REPLAY_AFTER_ACTUALS_NOT_LIVE",
        "forecast_week": forecast_week,
        "model_version": MODEL_VERSION,
        "selected_model": selected,
        "serving_artifact": file_used,
        "served_group_predictions": len(response),
        "group_week_score": group,
        "shop_week_score": shop,
        "alerts": alerts,
        "feature_history_fidelity": "RETROSPECTIVE_LATEST_DWH",
        "production_approval": "NOT_APPROVED",
    }
    (output / "serving_monitor_replay.json").write_text(
        json.dumps(monitor, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return monitor

