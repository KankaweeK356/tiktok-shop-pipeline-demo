"""Run Phase-3 ML training and check output evidence from real synthetic DWH."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .ml_backtest import run_backtesting


def main() -> None:
    root = Path("output/ml_history_ci")
    source = root / "source"
    warehouse = root / "main" / "er2.duckdb"
    out = root / "main" / "reports" / "ml_backtest"

    if not warehouse.is_file():
        raise FileNotFoundError(
            "Run python -m pipeline.ci_ml_history before the ML backtest."
        )
    result = run_backtesting(
        warehouse,
        source / "ml_marketing_plan.csv",
        out,
        source_run_id="mlhistory_initial_and_incremental",
    )
    assert result["data_classification"] == "SYNTHETIC_EDUCATIONAL_NOT_TIKTOK"
    assert result["model_use"] == "RESEARCH_ONLY_NOT_PRODUCTION_APPROVED"
    assert result["selected_by"] == "rolling_fold_validation_wape_not_test"
    assert len(result["rolling_validation_folds"]) == 3
    assert result["eligible_snapshots"] > 1000
    assert not any(
        f["validation_rows"] < 100 for f in result["rolling_validation_folds"]
    )

    scores = pd.read_csv(out / "test_overall_metrics.csv")
    per_group = pd.read_csv(out / "test_group_metrics.csv")
    per_horizon = pd.read_csv(out / "test_horizon_metrics.csv")
    selection = pd.read_csv(out / "model_selection_metrics.csv")
    preds = pd.read_csv(out / "test_predictions.csv")

    assert set(scores["model"]) == {
        "Seasonal Naive", "LightGBM Historical", "LightGBM Marketing-Aware"
    }
    assert len(per_group) == 3 * 5
    assert len(per_horizon) == 3 * 7
    assert set(preds["product_group_id"]) == {
        "PG01", "PG02", "PG03", "PG04", "PG05"
    }
    assert preds["as_of_date"].lt(preds["forecast_date"]).all()
    assert not preds.duplicated(
        ["model", "as_of_date", "forecast_date", "product_group_id"]
    ).any()
    assert preds["target_net_revenue"].ge(0).all()
    assert preds["predicted_net_revenue"].ge(0).all()
    assert scores["wape_pct"].notna().all()
    assert selection["validation_weighted_wape_pct"].notna().all()
    assert (out / "model_history.txt").is_file()
    assert (out / "model_marketing.txt").is_file()
    assert (out / "offline_feature_dataset.parquet").is_file()

    print(json.dumps({
        "status": "PASS",
        "dataset_rows": result["eligible_snapshots"],
        "training_fidelity": result["feature_history_fidelity"],
        "selected_by": result["selected_by"],
        "selected_model": result["selected_model"],
        "test_results": result["full_test_comparison"],
        "test_product_groups": int(per_group["product_group_id"].nunique()),
        "test_forecast_horizons": int(per_horizon["forecast_horizon"].nunique()),
        "artifact_directory": str(out),
        "warning": "Synthetic retrospective research-only; no causal effect inferred",
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
