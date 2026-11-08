"""Full 8-step educational MLOps demo evidence, using actual synthetic pipeline."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .ml_weekly import run_weekly
from .ml_weekly_serve import serve_monitor_replay


def main() -> None:
    root = Path("output/ml_history_ci")
    warehouse = root / "main" / "er2.duckdb"
    plans = root / "source" / "ml_marketing_plan.csv"
    if not warehouse.exists() or not plans.exists():
        raise FileNotFoundError("Run python -m pipeline.ci_ml_history first")

    output = root / "main" / "reports" / "ml_weekly"
    summary = run_weekly(warehouse, plans, output)
    monitor = serve_monitor_replay(output)

    folds = pd.read_csv(output / "weekly_rolling_folds.csv")
    test_scores = pd.read_csv(output / "weekly_test_metrics.csv")
    predictions = pd.read_csv(output / "weekly_test_predictions.csv")
    by_group = pd.read_csv(output / "weekly_test_by_group.csv")
    selection = pd.read_csv(output / "weekly_model_selection.csv")
    served = pd.read_csv(output / "serving_replay_predictions.csv")

    assert summary["data"] == "SYNTHETIC_EDUCATIONAL_NOT_TIKTOK"
    assert summary["fidelity"] == "RETROSPECTIVE_LATEST_DWH"
    assert summary["model_use"] == "DEMO_ONLY_NOT_PRODUCTION"
    assert summary["test_not_used_for_model_selection"]
    assert summary["weeks"] > 35
    assert summary["groups"] == 5
    assert len(folds) == 3 * 3
    assert len(selection) == 3
    assert len(test_scores) == 3
    assert len(by_group) == 3 * 5
    assert predictions["product_group_id"].nunique() == 5
    assert predictions["forecast_week_start"].nunique() == 8
    assert not predictions.duplicated(
        ["model", "forecast_week_start", "product_group_id"]
    ).any()
    assert test_scores["group_wape_pct"].notna().all()
    assert test_scores["shop_wape_pct"].notna().all()
    assert served["predicted_net_revenue_week"].ge(0).all()
    assert monitor["served_group_predictions"] == 5
    assert monitor["production_approval"] == "NOT_APPROVED"

    # Serving replay must agree with test predictions from the saved model,
    # NOT merely copying the already-computed predictions.
    expect = predictions.loc[
        predictions["model"].eq(summary["selected_by_validation"]) &
        predictions["forecast_week_start"].eq(monitor["forecast_week"]),
        ["product_group_id", "predicted_net_revenue_week"],
    ].sort_values("product_group_id").reset_index(drop=True)
    got = served[[
        "product_group_id", "predicted_net_revenue_week"
    ]].sort_values("product_group_id").reset_index(drop=True)
    assert len(got) == len(expect) == 5
    assert (got.product_group_id == expect.product_group_id).all()
    assert (
        (got.predicted_net_revenue_week - expect.predicted_net_revenue_week).abs()
        < 0.05
    ).all(), "Serialized model serving differs from held-out evaluation"

    print(json.dumps({
        "status": "PASS",
        "dataset_group_week_rows": summary["dataset_rows"],
        "weeks": summary["weeks"],
        "groups": summary["groups"],
        "validation_folds": len(summary["validation_folds"]),
        "selected_model": summary["selected_by_validation"],
        "final_test_group_and_shop_wape": [
            {"model": row["model"],
             "group_wape_pct": row["group_wape_pct"],
             "shop_wape_pct": row["shop_wape_pct"],
             "group_target_met": row["group_target_20pct"],
             "shop_target_met": row["shop_target_15pct"]}
            for row in summary["final_test_comparison"]
        ],
        "serving_replay": {
            "model": monitor["selected_model"],
            "week": monitor["forecast_week"],
            "group_count": monitor["served_group_predictions"],
            "monitoring_alerts": monitor["alerts"]
        },
        "artifact_directory": str(output),
        "model_use": "DEMO_ONLY",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
