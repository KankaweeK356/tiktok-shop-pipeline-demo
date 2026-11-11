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
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from .generate_ml_history import generate_ml_history
from .schema import ROOT

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
    history = generate_ml_history(target, seed=seed)
    source = ROOT / "source" / "incremental"
    shutil.move(str(target / "incremental"), str(target / "incremental_01"))
    # Keep original November records and corrections, but extend the mock ad
    # campaign validity to cover later deliveries in the same ER1 structure.
    campaigns = _read(target / "initial" / "Dim_Ad_Campaign.csv")
    campaigns["End_Date"] = "2027-04-30"
    campaigns.to_csv(target / "incremental_01" / "Dim_Ad_Campaign.csv",
                     index=False, encoding="utf-8-sig")

    templates = {name: _read(source / f"{name}.csv") for name in
                 ("Fact_Orders", "Fact_Order_Items", "Fact_Internal_Fulfillment")}
    nov_orders = templates["Fact_Orders"]
    nov_orders = nov_orders[nov_orders["Order_ID"].str.startswith("NOV")]
    all_orders = list(nov_orders["Order_ID"])
    results = []
    for index in range(2, 7):
        year = 2026 if index == 2 else 2027
        month = 12 if index == 2 else index - 2
        folder = target / f"incremental_{index:02d}"
        rng = random.Random(f"{seed}:{year}-{month:02d}")
        last_day = calendar.monthrange(year, month)[1]
        mapping = {oid: f"M{year}{month:02d}-{position:04d}"
                   for position, oid in enumerate(all_orders, 1)}
        days = {oid: 1 + rng.randrange(last_day) for oid in all_orders}
        orders = []
        for record in nov_orders.to_dict("records"):
            oid = record["Order_ID"]
            item = dict(record, Order_ID=mapping[oid], Voucher_ID="")
            for field in ("Order_Created_At", "Paid_At", "Shipped_At",
                          "Delivered_At", "Cancelled_At"):
                item[field] = _shift(item[field], days[oid], year, month)
            item["GMV_Total"] = item["Voucher_Seller_Cost"] = ""
            orders.append(item)
        _write(folder, "Fact_Orders", orders, list(nov_orders.columns))

        items = []
        for record in templates["Fact_Order_Items"].to_dict("records"):
            oid = record["Order_ID"]
            if oid not in mapping:
                continue
            old_item = record["Order_Item_ID"]
            new_item = mapping[oid] + old_item[len(oid):]
            item = dict(record, Order_ID=mapping[oid], Order_Item_ID=new_item,
                        Source_Order_Item_ID=new_item, Campaign_ID="",
                        Created_At=_shift(record["Created_At"], days[oid], year, month))
            for field in ("Base_Unit_Price_At_Sale", "Unit_Selling_Price",
                          "Campaign_Discount_Amount", "Total_Selling_Amount",
                          "Total_COGS", "Fee_Affiliate_Payout"):
                item[field] = ""
            item["Voucher_Allocated_Amount"] = "0"
            items.append(item)
        _write(folder, "Fact_Order_Items", items,
               list(templates["Fact_Order_Items"].columns))

        fulfillment = []
        for record in templates["Fact_Internal_Fulfillment"].to_dict("records"):
            oid = record["Order_ID"]
            if oid not in mapping:
                continue
            item = dict(record, Order_ID=mapping[oid],
                        Fulfillment_ID="FUL-" + mapping[oid],
                        Fulfillment_Timestamp=_shift(record["Fulfillment_Timestamp"],
                                                     days[oid], year, month))
            fulfillment.append(item)
        _write(folder, "Fact_Internal_Fulfillment", fulfillment,
               list(templates["Fact_Internal_Fulfillment"].columns))

        ad_columns = list(_read(source / "Fact_Marketing_Costs.csv").columns)
        ads = []
        for day in range(1, last_day + 1):
            for group in range(1, 6):
                spend = rng.choice((8, 12, 18, 25, 32, 45))
                ads.append({"Ad_Record_ID": f"AD-{year}{month:02d}{day:02d}-PG{group:02d}",
                            "Record_Date": f"{year}-{month:02d}-{day:02d}",
                            "Ad_Campaign_ID": f"AD{1 + group % 3}",
                            "Product_Group_ID": f"PG{group:02d}",
                            "Ad_Spend_Amount": spend,
                            "Impressions": spend * rng.randint(16, 30),
                            "Clicks": rng.randint(3, 24),
                            "Conversions": rng.randint(0, 5),
                            "Reported_Ads_GMV": "", "Reported_Ads_Orders": "",
                            "Reported_Revenue_Basis": ""})
        _write(folder, "Fact_Marketing_Costs", ads, ad_columns)
        sample_columns = list(_read(source / "Fact_Free_Samples.csv").columns)
        _write(folder, "Fact_Free_Samples", [], sample_columns)
        target_columns = list(_read(target / "initial" / "Ref_Business_Target.csv").columns)
        _write(folder, "Ref_Business_Target", [{"Target_Year_Month": f"{year}-{month:02d}",
               "Revenue_Target": 120000, "Minimum_Profit_Protection_Rate": 0.10}], target_columns)
        results.append({"batch": folder.name, "month": f"{year}-{month:02d}",
                        "orders": len(orders), "ads_rows": len(ads)})
    (target / "source_manifest.json").write_text(json.dumps({
        "classification": "SYNTHETIC_EDUCATIONAL_NOT_TIKTOK",
        "seed": seed, "batches": list(BATCHES),
        "initial_history_start": history["historical_start"],
        "initial_history_end": "2026-10-31", "increments": results,
        "note": "Generated Source CSV; reset preserves all deliveries."
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"initial_history": history["historical_start"],
            "batches": list(BATCHES), "increments": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="output/classroom_source")
    args = parser.parse_args()
    print(json.dumps(build(ROOT / args.output), ensure_ascii=False))
