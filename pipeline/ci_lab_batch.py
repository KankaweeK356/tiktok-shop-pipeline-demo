"""Run all five genuine classroom stages in one GitHub Actions worker."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
import duckdb

from .ci_lab_stage import STATE_PATH, run_stage
from .orchestrator import STAGES


def run_stage_and_save(batch: str, stage: str) -> dict:
    if batch not in ("initial", "incremental"):
        raise ValueError("Invalid batch")
    if stage not in STAGES:
        raise ValueError("Invalid stage")
    workspace = STATE_PATH.parent
    result_dir = workspace / "batch_results" / batch
    result_dir.mkdir(parents=True, exist_ok=True)
    previous = result_dir / f"{stage}.json"
    if previous.is_file():
        receipt = json.loads(previous.read_text(encoding="utf-8"))
        if receipt.get("batch") == batch and receipt.get("stage") == stage:
            shutil.copyfile(previous, workspace / "last_step_result.json")
            print(json.dumps({"stage": stage, "status": "RESTORED"}), flush=True)
            return receipt
    receipt = run_stage(stage, batch)
    shutil.copyfile(workspace / "last_step_result.json", previous)
    print(json.dumps({"stage": stage, "status": "SUCCESS"}), flush=True)
    return receipt


def finalize(batch: str) -> dict:
    workspace = STATE_PATH.parent
    result_dir = workspace / "batch_results" / batch
    receipts = [json.loads((result_dir / f"{stage}.json").read_text(encoding="utf-8"))
                for stage in STAGES]
    if any(item["batch"] != batch or item["stage"] != stage
           for item, stage in zip(receipts, STAGES)):
        raise RuntimeError("Batch stage evidence does not match")
    receipt = receipts[-1]
    results = [{"stage": item["stage"], "evidence": item["evidence"]}
               for item in receipts]
    summary = {"batch": batch, "status": "SUCCESS", "cycle": receipt["cycle"],
               "run_id": receipt["run_id"], "stages": results,
               "elapsed_seconds": receipt["result"].get("elapsed_seconds"),
               "paid_sales_rows": receipt["result"].get("paid_sales_rows"),
               "net_revenue": receipt["result"].get("net_revenue")}
    def order_count(item: dict) -> int:
        tables = item["evidence"]["output"].get("tables", [])
        return next(int(table["rows"]) for table in tables
                    if table["name"] == "Fact_Orders")
    summary["orders_after"] = order_count(receipts[0])
    if batch == "incremental":
        initial = json.loads((workspace / "batch_results" / "initial" / "ingest.json")
                             .read_text(encoding="utf-8"))
        summary["orders_before"] = order_count(initial)
        summary["orders_added"] = summary["orders_after"] - summary["orders_before"]
    else:
        summary["orders_before"] = 0
        summary["orders_added"] = summary["orders_after"]
    with duckdb.connect(str(workspace / "er2.duckdb"), read_only=True) as db:
        total, distinct = db.execute(
            "SELECT COUNT(*), COUNT(DISTINCT Source_Order_Item_ID) "
            "FROM Fact_Sales_Order_Item").fetchone()
    summary["no_duplicate_sales_items"] = total == distinct
    if not summary["no_duplicate_sales_items"]:
        raise RuntimeError("Warehouse contains duplicate sales item IDs")
    (workspace / "batch_result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", choices=("initial", "incremental"), required=True)
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.finalize:
        finalize(args.batch)
    elif args.stage:
        run_stage_and_save(args.batch, args.stage)
    else:
        raise ValueError("Choose --stage or --finalize")


if __name__ == "__main__":
    main()
