"""Reproducible 12-month synthetic history for Marketing-Aware ML.

This is an OPTIONAL profile; the original October/November data and CI stay intact.
Historical commerce/Ads/Campaigns follow Source -> SQLite -> Lake -> DuckDB.
Planning records remain a separate synthetic ML source (not a 26th OLTP table).

NOT TikTok data and NOT a claim of causal Ads/Discount response.
"""
from __future__ import annotations

import argparse
import calendar
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .generate import GROUPS, generate
from .schema import ROOT

HISTORY_START = date(2025, 11, 1)
HISTORY_END = date(2026, 9, 30)
OCTOBER_START = date(2026, 10, 1)
NOVEMBER_INCREMENTAL = date(2026, 11, 1)
SCENARIO_ID = "SYNTHETIC_HISTORY_V1"


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def _append(path: Path, records: list[dict]) -> None:
    if not records:
        return
    df = pd.concat([_read(path), pd.DataFrame(records)], ignore_index=True)
    if df.columns.tolist() != _read(path).columns.tolist():
        raise AssertionError(f"Source CSV schema changed unexpectedly: {path.name}")
    if df.isna().all(axis=1).any():
        raise AssertionError(f"Fully empty source row: {path.name}")
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _update_start(path: Path, field: str, earliest: date) -> None:
    df = _read(path)
    df[field] = earliest.isoformat()
    df.to_csv(path, index=False, encoding="utf-8-sig")


def _month_starts(start: date, end: date):
    cur = start.replace(day=1)
    while cur <= end:
        yield cur
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)


def _days(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def generate_ml_history(
    target: Path | str | None = None,
    *,
    seed: int = 8102,
    start: date = HISTORY_START,
    end: date = HISTORY_END,
    base_orders_per_group_day: float = 1.2,
    n_initial: int = 800,
    n_incremental: int = 100,
) -> dict:
    """Add pre-October history while retaining original demo's Oct/Nov cases.

    Default output is NOT repo/source; call with a dedicated destination.
    A full month or sequence of months ending before Oct 2026 is required.
    """
    start = date.fromisoformat(start) if isinstance(start, str) else start
    end = date.fromisoformat(end) if isinstance(end, str) else end
    if start < date(2025, 1, 1) or end >= OCTOBER_START or start > end:
        raise ValueError("ML history must be between 2025-01-01 and 2026-09-30")
    if start.day != 1 or end.day != calendar.monthrange(end.year, end.month)[1]:
        raise ValueError("ML history range must cover whole calendar months")
    if base_orders_per_group_day < 0 or base_orders_per_group_day > 15:
        raise ValueError("base_orders_per_group_day must be in [0, 15]")
    if n_initial < 30 or n_incremental < 30:
        raise ValueError("Keep minimum original demo cases for pending and corrections")

    base = Path(target) if target else ROOT / "output" / "ml_history" / "source"
    base.mkdir(parents=True, exist_ok=True)
    original = generate(base, n_initial=n_initial, n_incremental=n_incremental, seed=seed)
    initial = base / "initial"

    sku_df = _read(initial / "Dim_SKU.csv")
    sku_by_group = defaultdict(list)
    for x in sku_df.itertuples(index=False):
        sku_by_group[x.Product_Group_ID].append(x.SKU_ID)
    original_bridge = _read(initial / "Bridge_Campaign_Product_Group.csv")
    prices = {group: price for group, _name, price in GROUPS}

    # Historical pricing campaigns: non-overlapping 5-9 and 18-22 windows.
    historical_campaigns, historical_enrolments = [], []
    campaign_by_group_day = {}
    for month in _month_starts(start, end):
        for wave, lo, hi in (("A", 5, 9), ("B", 18, 22)):
            cid = f"HIST-{month:%Y%m}-{wave}"
            first = date(month.year, month.month, lo)
            last = date(month.year, month.month, hi)
            historical_campaigns.append({
                "Campaign_ID": cid,
                "Campaign_Name": f"Synthetic {month:%Y-%m} Wave {wave}",
                "Campaign_Type": "Promotion" if wave == "A" else "Flash Sale",
                "Start_Date": first.isoformat(),
                "End_Date": last.isoformat(),
            })
            for group, _, base_price in GROUPS:
                rule_rng = random.Random(f"{seed}:campaign:{cid}:{group}")
                if rule_rng.random() < 0.27:
                    continue
                discount = rule_rng.choice((0.05, 0.08, 0.10, 0.12, 0.15, 0.18))
                selling_price = round(base_price * (1 - discount), 2)
                historical_enrolments.append({
                    "Enrollment_ID": f"EN-{cid}-{group}",
                    "Campaign_ID": cid,
                    "Product_Group_ID": group,
                    "Campaign_Selling_Price": selling_price,
                    "Effective_From": first.isoformat(),
                    "Effective_To": last.isoformat(),
                    "Status": "Active",
                })
                for day in _days(first, last):
                    campaign_by_group_day[(day, group)] = (
                        round((base_price - selling_price) / base_price, 4)
                    )
    _append(initial / "Dim_Campaign.csv", historical_campaigns)
    _append(initial / "Bridge_Campaign_Product_Group.csv", historical_enrolments)

    # Existing October + November campaigns are retained; build known plans from
    # their actual source price rules, rather than inventing a group-wide SKU price.
    for x in original_bridge.itertuples(index=False):
        base_price = prices[x.Product_Group_ID]
        discount = round(
            (base_price - float(x.Campaign_Selling_Price)) / base_price, 4
        )
        for day in _days(
            date.fromisoformat(x.Effective_From),
            date.fromisoformat(x.Effective_To),
        ):
            campaign_by_group_day[(day, x.Product_Group_ID)] = discount

    # Extend *existing mock* rule lifetimes for older synthetic transactions.
    for file_name, field in (
        ("Ref_Affiliate_Commission_Rule.csv", "Effective_From"),
        ("Ref_Platform_Fee_Estimate_Rule.csv", "Effective_From"),
        ("Ref_Cost_Policy.csv", "Effective_From"),
        ("Dim_Ad_Campaign.csv", "Start_Date"),
    ):
        _update_start(initial / file_name, field, start)

    # FIFO receipt must occur before the earliest historic paid sales.
    receipt_date = start - timedelta(days=4)
    _append(initial / "Fact_Goods_Receipt.csv", [{
        "Goods_Receipt_ID": "GR-ML-HIST",
        "Receipt_Date": f"{receipt_date.isoformat()} 10:00:00",
        "Supplier_ID": "SUP-MOCK",
        "Reference_PO_ID": "PO-ML-HIST-001",
        "Source_System": "MOCK",
    }])
    receipt_items = []
    for row in sku_df.itertuples(index=False):
        unit = round(prices[row.Product_Group_ID] * 0.4, 2)
        qty = 10000
        receipt_items.append({
            "Goods_Receipt_Item_ID": f"G-HIST-{row.SKU_ID}",
            "Goods_Receipt_ID": "GR-ML-HIST",
            "SKU_ID": row.SKU_ID,
            "Received_Qty": qty,
            "Unit_Cost": unit,
            "Total_Cost": round(unit * qty, 2),
            "Remaining_Qty": qty,
            "Lot_No": "LOT-ML-HIST",
        })
    _append(initial / "Fact_Goods_Receipt_Items.csv", receipt_items)

    historical_targets = []
    for i, month in enumerate(_month_starts(start, end)):
        # Goal set independently of each month's realized sales. Not a target leak.
        historical_targets.append({
            "Target_Year_Month": f"{month:%Y-%m}",
            "Revenue_Target": 50000 + 2000 * (i % 4),
            "Minimum_Profit_Protection_Rate": 0.10,
        })
    _append(initial / "Ref_Business_Target.csv", historical_targets)

    new_headers, new_items, new_fulfillment, new_ads, plans = [], [], [], [], []
    counts = defaultdict(int)
    np_rng = np.random.default_rng(seed + 312)
    first_plan = start
    last_plan = NOVEMBER_INCREMENTAL

    # For each date/group, create a frozen 35-day-ahead plan known *before* the sale date.
    # Realized spend may differ from budget; order demand has seasonality and
    # stochastic variation. These are *simulation rules*, NOT learned effects.
    for day in _days(first_plan, last_plan):
        in_history = start <= day <= end
        if not in_history and day < OCTOBER_START:
            continue
        for group, _, _base_price in GROUPS:
            prng = random.Random(f"{seed}:plan:{day}:{group}")
            discount = campaign_by_group_day.get((day, group), 0.0)
            planned_budget = prng.choice((0, 8, 18, 32, 45, 60))
            if discount > 0:
                planned_budget += 10
            if day.weekday() >= 5:
                planned_budget += 5
            plans.append({
                "scenario_id": SCENARIO_ID,
                "product_group_id": group,
                "plan_date": day.isoformat(),
                "plan_version": 1,
                "planned_ads_spend": planned_budget,
                "planned_campaign_discount_rate": discount,
                "plan_status": "HISTORICAL",
                "plan_source": "SYNTHETIC_HISTORICAL_PLAN",
                "recorded_at": f"{(day - timedelta(days=35)).isoformat()}T17:00:00+07:00",
            })
            if not in_history:
                # October/Nov remain controlled by the established source demo.
                continue

            realized_ads = round(
                planned_budget * prng.uniform(0.78, 1.10), 2
            )
            new_ads.append({
                "Ad_Record_ID": f"AD-HIST-{day:%Y%m%d}-{group}",
                "Record_Date": day.isoformat(),
                "Ad_Campaign_ID": f"AD{1 + int(group[-1]) % 3}",
                "Product_Group_ID": group,
                "Ad_Spend_Amount": realized_ads,
                "Impressions": prng.randint(30, 300) + int(realized_ads * 35),
                "Clicks": prng.randint(1, 12) + int(realized_ads * 0.9),
                "Conversions": prng.randint(0, 6),
                "Reported_Ads_GMV": None,
                "Reported_Ads_Orders": None,
                "Reported_Revenue_Basis": None,
            })

            seasonal = 0.35 if day.weekday() >= 5 else 0
            seasonal += 0.15 if day.month in (1, 6, 11, 12) else 0
            # Confounded marketing signals and randomness: avoid a trivial
            # one-to-one association of planned Ads or discount with sales.
            mean_orders = max(
                0.05,
                base_orders_per_group_day
                + seasonal
                + 0.008 * planned_budget
                + (0.35 if discount else 0)
                + np_rng.normal(0, 0.18),
            )
            daily_orders = int(np_rng.poisson(mean_orders))
            counts["historical_days"] += 1 if group == GROUPS[0][0] else 0
            counts["ads_rows"] += 1

            for ordinal in range(daily_orders):
                oid = f"H{day:%Y%m%d}-{group}-{ordinal+1:03d}"
                created = datetime.combine(day, datetime.min.time()) + timedelta(
                    minutes=8 * 60 + prng.randint(0, 12 * 60)
                )
                paid = created + timedelta(minutes=prng.randint(5, 60))
                shipped = paid + timedelta(hours=3)
                delivered = shipped + timedelta(days=2)
                status = prng.choice(("Paid", "Shipped", "Delivered"))
                new_headers.append({
                    "Order_ID": oid,
                    "Order_Created_At": created.isoformat(" "),
                    "Current_Status": status,
                    "Voucher_ID": None,  # existing voucher rules start Oct 2026
                    "GMV_Total": None,
                    "Voucher_Seller_Cost": None,
                    "Shipping_Fee_Collected": 0,
                    "Shipping_Mode": "TikTok_Platform",
                    "Paid_At": paid.isoformat(" "),
                    "Shipped_At": shipped.isoformat(" ") if status != "Paid" else None,
                    "Delivered_At": delivered.isoformat(" ") if status == "Delivered" else None,
                    "Cancelled_At": None,
                })
                skus = prng.sample(
                    sku_by_group[group], k=1 if prng.random() < 0.83 else 2
                )
                for line_no, sku in enumerate(skus, start=1):
                    new_items.append({
                        "Order_Item_ID": f"{oid}-I{line_no}",
                        "Source_Order_Item_ID": f"{oid}-I{line_no}",
                        "Order_ID": oid,
                        "SKU_ID": sku,
                        "Quantity": prng.choice((1, 1, 1, 2)),
                        "Creator_ID": (
                            f"CR{prng.randint(1, 8):02d}"
                            if prng.random() < 0.28 else None
                        ),
                        "Campaign_ID": None,
                        "Base_Unit_Price_At_Sale": None,
                        "Unit_Selling_Price": None,
                        "Campaign_Discount_Amount": None,
                        "Voucher_Allocated_Amount": 0,
                        "Total_Selling_Amount": None,
                        "Total_COGS": None,
                        "Fee_Affiliate_Payout": None,
                        "Created_At": created.isoformat(" "),
                    })
                new_fulfillment.append({
                    "Fulfillment_ID": f"FUL-{oid}",
                    "Order_ID": oid,
                    "Secondary_Packaging_Cost": prng.choice((2, 3, 4)),
                    "Packing_Labor_Cost": prng.choice((4, 5, 6)),
                    "Actual_Shipping_Cost": prng.choice((0, 4, 6)),
                    "Fulfillment_Timestamp": (paid + timedelta(hours=1)).isoformat(" "),
                })
                counts["orders"] += 1
                counts["order_items"] += len(skus)
    for table, rows in (
        ("Fact_Orders", new_headers),
        ("Fact_Order_Items", new_items),
        ("Fact_Internal_Fulfillment", new_fulfillment),
        ("Fact_Marketing_Costs", new_ads),
    ):
        _append(initial / f"{table}.csv", rows)

    pd.DataFrame(plans).to_csv(
        base / "ml_marketing_plan.csv", index=False, encoding="utf-8-sig"
    )
    (base / "ML_HISTORY_README.md").write_text(
        "# Synthetic ML history (no TikTok API)\n"
        f"Seed: {seed}\n"
        f"Historical paid order range: {start} to {end}\n"
        "The original October 2026 and November incremental examples are retained.\n"
        "Plans were GENERATED 35 days before planned dates (synthetic), NOT sourced from real planning systems.\n"
        "Actual Ads spend varies around the generated plan; demand includes stochastic seasonality.\n"
        "These synthetic patterns are NOT evidence of a real-world advertising causal effect.\n"
        "Do NOT mark a retrospective latest-DWH feature snapshot as point-in-time verified.\n",
        encoding="utf-8",
    )
    return {
        "profile": "ML_HISTORICAL_SYNTHETIC",
        "seed": seed,
        "historical_start": start.isoformat(),
        "historical_end": end.isoformat(),
        "historical_orders": counts["orders"],
        "historical_order_items": counts["order_items"],
        "historical_ads_rows": counts["ads_rows"],
        "marketing_plan_rows": len(plans),
        "historic_campaign_enrolments": len(historical_enrolments),
        "historic_monthly_targets": len(historical_targets),
        "original_demo": original,
        "source": str(base),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate 12-month synthetic ML source")
    parser.add_argument("--output", default="output/ml_history/source")
    parser.add_argument("--seed", type=int, default=8102)
    parser.add_argument("--base-orders-per-group-day", type=float, default=1.2)
    args = parser.parse_args()
    import json
    result = generate_ml_history(
        args.output, seed=args.seed,
        base_orders_per_group_day=args.base_orders_per_group_day,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
