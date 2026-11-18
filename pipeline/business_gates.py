"""Shop-month Business KPI gates (Revenue / Profit Protection / Marketing GAP) from Published ER2 rollups.

Pure functions: no I/O except reading the pre-configured planning seed. KPI FAIL is a business
outcome (data is still published); only missing/incomplete inputs yield INCOMPLETE / MISSING_*.
"""
from __future__ import annotations

import json
from pathlib import Path

from .schema import ROOT

PLANNING_PATH = ROOT / "dashboard" / "data" / "planning_targets_v1.json"


def load_planning(path: Path | None = None) -> dict:
    return json.loads((path or PLANNING_PATH).read_text(encoding="utf-8"))


def _num(value):
    return None if value is None else float(value)


def marketing_gap(row: dict) -> dict:
    """GAP = (Campaign reduction + Voucher + Affiliate + Ads + Free sample) / Gross reference sales."""
    parts = {k: _num(row.get(k)) for k in ("campaign_reduction", "voucher", "affiliate", "ads", "sample")}
    gross = _num(row.get("gross"))
    if row.get("incomplete_rows") or any(v is None for v in parts.values()) or not gross or gross <= 0:
        return {"status": "INCOMPLETE", "rate_pct": None, "numerator": None, "components": parts}
    numerator = round(sum(parts.values()), 2)
    return {"status": "COMPUTED", "rate_pct": round(100.0 * numerator / gross, 2), "numerator": numerator, "components": parts}


def shop_month_gates(row: dict, kpi: dict | None, planning: dict) -> dict:
    """`row` = monthly mart rollup, `kpi` = View_Shop_Monthly_KPI row for the same month (or None)."""
    month = row["month"]
    plan = planning["months"].get(month)
    net, gross, profit = _num(row.get("net")), _num(row.get("gross")), _num(row.get("profit"))
    incomplete = bool(row.get("incomplete_rows")) or profit is None
    er2_target = _num((kpi or {}).get("target"))
    target = er2_target if er2_target else (plan or {}).get("revenue_target_thb")
    revenue = {"status": "MISSING_TARGET", "target": target, "gap": None, "achievement_pct": None}
    if target and target > 0 and net is not None:
        revenue = {"status": "PASS" if net >= target else "FAIL", "target": target, "gap": round(net - target, 2),
                   "achievement_pct": round(100.0 * net / target, 2)}
    min_rate = (plan or {}).get("minimum_profit_protection_rate", _num((kpi or {}).get("min_protection_rate")))
    protection = {"status": "INCOMPLETE", "rate_pct": None, "required": None, "headroom": None}
    if not incomplete and gross and gross > 0 and min_rate is not None:
        required = round(gross * min_rate, 2)
        protection = {"status": "PASS" if profit >= required else "FAIL", "rate_pct": round(100.0 * profit / gross, 2),
                      "required": required, "headroom": round(profit - required, 2)}
    gap = marketing_gap(row)
    max_rate = (plan or {}).get("maximum_marketing_gap_rate")
    if gap["status"] == "COMPUTED":
        gap["status"] = "MISSING_POLICY" if max_rate is None else ("PASS" if gap["rate_pct"] <= 100 * max_rate else "FAIL")
    gap["max_rate_pct"] = None if max_rate is None else round(100 * max_rate, 2)
    discrepancy = bool(er2_target and plan and abs(er2_target - plan["revenue_target_thb"]) > 0.005)
    return {"month": month, "revenue": revenue, "profit_protection": protection, "marketing_gap": gap,
            "profit": None if incomplete else profit, "profit_data_status": "INCOMPLETE" if incomplete else "COMPLETE",
            "target_policy": {"version": planning["policy_version"], "label": planning["label"],
                              "source_sha256": planning["source_sha256"], "er2_target_discrepancy": discrepancy}}
