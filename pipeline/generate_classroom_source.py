"""Build the seven deterministic CSV deliveries used by the classroom lab.

The generated files are Source, separate from Neon and from the worker's
SQLite/Parquet/DuckDB outputs. A reset discards outputs, never these inputs.
"""
from __future__ import annotations

import argparse
import calendar
import json
import random
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from .generate_ml_history import SCENARIO_ID, generate_ml_history
from .er1 import SOURCE_ORDER
from .schema import ROOT, parse_dbml

BATCH_MONTHS = [date(2026, month, 1) for month in range(1, 8)]
INITIAL_HISTORY_START = date(2026, 1, 1)
INITIAL_HISTORY_END = date(2026, 1, 31)
SOURCE_DATA_END = date(2026, 7, 31)
BATCHES = ("initial",) + tuple(f"incremental_{i:02d}" for i in range(1, 7))


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def _write(folder: Path, name: str, rows: list[dict], columns: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=columns).to_csv(folder / f"{name}.csv", index=False,
                                                   encoding="utf-8-sig")


def _shift(value: str, new_day: int, year: int, month: int) -> str:
    if not value:
        return value
    stamp = datetime.fromisoformat(value)
    # Nov 1 source records are distributed over the following month. Retain
    # each record's local time and relative fulfillment delay.
    shifted = datetime(year, month, new_day) + (stamp - datetime(2026, 11, 1))
    return shifted.isoformat(" ") if " " in value else shifted.date().isoformat()


def build(target: Path, seed: int = 8102) -> dict:
    target = Path(target)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    # Run 1 is January 2026 only. Later deliveries add exactly one new month
    # each. ML training stays unavailable until enough real Warehouse months
    # have accumulated for chronological Train/Validation/Test evaluation.
    history = generate_ml_history(target, seed=seed,
                                  start=INITIAL_HISTORY_START,
                                  end=SOURCE_DATA_END)
    initial = target / "initial"
    tables, _ = parse_dbml(ROOT / "schemas" / "ER1_V3.dbml")
    columns = {table.name: [column.name for column in table.columns] for table in tables}
    derived = {"Fact_FIFO_Allocation", "Fact_Order_Platform_Fees",
               "Fact_Stock_Movement", "Fact_Inventory_Snapshot"}
    source_frames = {}
    for table in SOURCE_ORDER:
        path = initial / (table + ".csv")
        source_frames[table] = (_read(path) if path.is_file()
                                else pd.DataFrame(columns=columns[table]))

    order_frame = source_frames["Fact_Orders"]
    item_frame = source_frames["Fact_Order_Items"]
    result_batches = []
    for index, month_start in enumerate(BATCH_MONTHS):
        month = month_start.strftime("%Y-%m")
        folder = target / ("initial" if index == 0 else f"incremental_{index:02d}")
        folder.mkdir(parents=True, exist_ok=True)
        for table in SOURCE_ORDER:
            frame = source_frames[table]
            if table == "Fact_Orders":
                order_months = frame.Order_Created_At.astype(str).str[:7]
                chosen = frame[order_months.eq("2026-01")
                               if index == 0 else order_months.eq(month)]
            elif table == "Fact_Order_Items":
                order_months = order_frame.Order_Created_At.astype(str).str[:7]
                in_delivery = (order_months.eq("2026-01")
                               if index == 0 else order_months.eq(month))
                ids = set(order_frame.loc[in_delivery, "Order_ID"])
                chosen = frame[frame.Order_ID.isin(ids)]
            elif table == "Fact_Internal_Fulfillment":
                order_months = order_frame.Order_Created_At.astype(str).str[:7]
                in_delivery = (order_months.eq("2026-01")
                               if index == 0 else order_months.eq(month))
                ids = set(order_frame.loc[in_delivery, "Order_ID"])
                chosen = frame[frame.Order_ID.isin(ids)]
            elif table == "Fact_Marketing_Costs":
                dates = frame.Record_Date.astype(str).str[:7]
                chosen = frame[dates.eq("2026-01")
                               if index == 0 else dates.eq(month)]
            elif table == "Fact_Free_Samples":
                dates = frame.Request_Date.astype(str).str[:7]
                chosen = frame[dates.eq("2026-01")
                               if index == 0 else dates.eq(month)]
            elif table == "Fact_Claim_Header":
                dates = frame.Claim_Date.astype(str).str[:7]
                chosen = frame[dates.eq("2026-01")
                               if index == 0 else dates.eq(month)]
            elif table == "Fact_Claim_Details":
                claims = source_frames["Fact_Claim_Header"]
                claim_months = claims.Claim_Date.astype(str).str[:7]
                in_delivery = (claim_months.eq("2026-01")
                               if index == 0 else claim_months.eq(month))
                claim_ids = set(claims.loc[in_delivery, "Claim_ID"])
                chosen = frame[frame.Claim_ID.isin(claim_ids)]
            elif table == "Ref_Business_Target":
                target_months = frame.Target_Year_Month.astype(str)
                chosen = frame[target_months.eq("2026-01")
                               if index == 0 else target_months.eq(month)]
            elif table in ("Fact_Goods_Receipt", "Fact_Goods_Receipt_Items"):
                chosen = frame if index == 0 else frame.iloc[0:0]
            elif table.startswith(("Dim_", "Bridge_", "Ref_")):
                chosen = frame if index == 0 else frame.iloc[0:0]
            else:
                chosen = frame.iloc[0:0]
            chosen.to_csv(folder / (table + ".csv"), index=False,
                          columns=columns[table], encoding="utf-8-sig")
        order_months = order_frame.Order_Created_At.astype(str).str[:7]
        batch_orders = order_frame.loc[
            order_months.eq("2026-01") if index == 0
            else order_months.eq(month)]
        batch_order_ids = set(batch_orders.Order_ID)
        batch_items = item_frame[item_frame.Order_ID.isin(batch_order_ids)]
        result_batches.append({"batch": folder.name, "month": month,
                               "orders": int(len(batch_orders)),
                               "items": int(len(batch_items))})
    shutil.rmtree(target / "incremental", ignore_errors=True)
    # ML planning rows stay separate from ER1, but span the exact warehouse history.
    plan_path = target / "ml_marketing_plan.csv"
    plans = pd.read_csv(plan_path)
            plans = plans[plans.plan_date.astype(str).str[:7].between("2026-01", "2026-07")]
    plans.to_csv(plan_path, index=False, encoding="utf-8-sig")
    (target / "source_manifest.json").write_text(json.dumps({
        "seed": seed,
        "run_1_month": "2026-01",
        "incremental_months": [x["month"] for x in result_batches[1:]],
        "source_tables": SOURCE_ORDER, "er1_tables": len(tables),
        "derived_tables": sorted(derived), "batches": result_batches,
        "master_policy": "Master/Ref/Bridge supplied on Run 1; monthly Ref_Business_Target and facts are supplied in each incremental delivery.",
        "classification": "SYNTHETIC_EDUCATIONAL_NOT_TIKTOK",
        "note": "Every delivery has the same 21 ER1 Source CSVs. Run 1 contains January 2026 only; each later delivery adds one month. ML waits until the Warehouse has enough monthly data for chronological evaluation. Four derived ER1 tables are created by pipeline code; no ER changes. Reset preserves Source."
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"historical_start": history["historical_start"],
            "batches": result_batches, "source_tables": SOURCE_ORDER,
            "derived_tables": sorted(derived), "er1_tables": len(tables)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="output/classroom_source")
    args = parser.parse_args()
    print(json.dumps(build(ROOT / args.output), ensure_ascii=False))
