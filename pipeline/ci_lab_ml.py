"""Train and inspect ML from the current classroom Warehouse artifact only."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .ml_weekly import run_weekly
from .ml_weekly_serve import serve_monitor_replay
from .schema import ROOT


def main() -> None:
    warehouse = ROOT / "output" / "classroom_lab" / "er2.duckdb"
    source = ROOT / "output" / "classroom_source"
    result_dir = ROOT / "output" / "classroom_ml"
    if not warehouse.is_file() or not (source / "ml_marketing_plan.csv").is_file():
        raise FileNotFoundError("Current Warehouse and frozen synthetic plans are required")
    receipt = json.loads((ROOT / "output" / "classroom_lab" / "batch_result.json")
                         .read_text(encoding="utf-8"))
    summary = run_weekly(warehouse, source / "ml_marketing_plan.csv", result_dir)
    monitor = serve_monitor_replay(result_dir)
    feature = pd.read_parquet(result_dir / "weekly_training_dataset.parquet")
    test = pd.read_csv(result_dir / "weekly_test_predictions.csv")
    metrics = pd.read_csv(result_dir / "weekly_test_metrics.csv")
    public = {
        "classification": "SYNTHETIC_EDUCATIONAL_NOT_TIKTOK",
        "warehouse_run_id": receipt["run_id"],
        "warehouse_cycle": receipt["cycle"],
        "warehouse_batch": receipt["batch"],
        "source": "CURRENT_CLASSROOM_WAREHOUSE",
        "summary": summary,
        "monitor": monitor,
        "feature_preview": json.loads(feature.head(12).to_json(orient="records")),
        "test_metrics": json.loads(metrics.to_json(orient="records")),
        "test_predictions": json.loads(test.head(20).to_json(orient="records")),
    }
    (result_dir / "classroom_ml_result.json").write_text(
        json.dumps(public, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"source": public["source"], "dataset_rows": summary["dataset_rows"],
                      "selected_model": summary["selected_by_validation"]}))


if __name__ == "__main__":
    main()
