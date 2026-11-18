"""Point-in-time feature table builder.

One row per (origin month, group). Every feature of a row uses ONLY data of months <= its origin month; the label is the net revenue
of the NEXT month and is present only for origins whose label month is already published. The last origin (= the cutoff month) is the
inference row for the target month: it has no label. Slicing "train for origin i" therefore needs no extra filtering of the future.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from ..monthly_forecast import ForecastError, days_in, month_add
from .definitions import DUMMIES, FEATURE_VERSION, FEATURES, FORBIDDEN_TOKENS, GROUPS

ROW_FIELDS = ("month", "group", "net_revenue", "gross_reference_sales", "ads_cost", "campaign_reduction", "voucher_discount", "affiliate_cost")


def read_published_marketing_months(er2_path: Path) -> list[dict]:
    """Monthly roll-up per group from the Published ER2 daily mart (grain: month x group). Read-only; ER2 is not changed."""
    import duckdb
    with duckdb.connect(str(er2_path), read_only=True) as db:
        rows = db.execute("""
            SELECT d.Year_Month, m.Product_Group_ID, SUM(m.Net_Revenue), SUM(m.Gross_Reference_Sales), SUM(m.Ads_Cost),
                   SUM(m.Campaign_Price_Reduction), SUM(m.Voucher_Discount), SUM(m.Affiliate_Cost)
              FROM Mart_Product_Group_Daily_Performance m
              JOIN Dim_Date d ON d.Date_Key = m.Date_Key
             GROUP BY 1, 2 ORDER BY 1, 2""").fetchall()
    return [dict(zip(ROW_FIELDS, [r[0], r[1], *[None if v is None else float(v) for v in r[2:]]])) for r in rows]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def input_hash(rows: list[dict]) -> str:
    canonical = json.dumps([[r["month"], r["group"], *[None if r.get(k) is None else round(float(r[k]), 2) for k in ROW_FIELDS[2:]]]
                            for r in sorted(rows, key=lambda r: (r["month"], r["group"]))])
    return hashlib.sha256(canonical.encode()).hexdigest()


def _ratio(num, den):
    if num is None or den is None or float(den) <= 0:
        return None                                    # unknown stays unknown: never filled with 0
    return float(num) / float(den)


def build_feature_table(rows: list[dict], target_month: str) -> dict:
    """Return {"months", "cutoff", "table": [row dict ...]}; raises ForecastError on leakage, gaps or an unpublished cutoff."""
    for name in (f["name"] for f in FEATURES):
        if any(token in name for token in FORBIDDEN_TOKENS):
            raise ForecastError("FORECAST_FORBIDDEN_FEATURE", name)
    if not rows:
        raise ForecastError("FORECAST_NO_PUBLISHED_DATA")
    cutoff = month_add(target_month, -1)
    months = sorted({r["month"] for r in rows})
    if months[-1] > cutoff:
        raise ForecastError("FORECAST_LEAKAGE", f"data for {months[-1]} is later than cutoff {cutoff}")
    if months[-1] != cutoff:
        raise ForecastError("FORECAST_CUTOFF_NOT_PUBLISHED", f"published through {months[-1]}, need {cutoff}")
    if months != [month_add(months[0], i) for i in range(len(months))]:
        raise ForecastError("FORECAST_MONTH_GAP", f"published months are not contiguous: {months}")
    by = {(r["month"], r["group"]): r for r in rows}
    if any((m, g) not in by for m in months for g in GROUPS):
        raise ForecastError("FORECAST_INCOMPLETE_GROUP_MONTHS", "every published month needs all five groups")
    for r in rows:
        if r["group"] not in GROUPS:
            raise ForecastError("FORECAST_UNKNOWN_GROUP", r["group"])
    net = {g: [float(by[(m, g)]["net_revenue"]) for m in months] for g in GROUPS}
    table = []
    for i, origin in enumerate(months):
        label_month = months[i + 1] if i + 1 < len(months) else target_month
        for g in GROUPS:
            hist = net[g][: i + 1]                    # months <= origin only
            cur = by[(origin, g)]
            base2 = hist[-3] if len(hist) >= 3 else None
            row = {"origin_month": origin, "label_month": label_month, "known_at": date(int(origin[:4]), int(origin[5:]), days_in(origin)).isoformat(),
                   "group": g, "lag1_group_net": hist[-1], "trailing3_group_net_mean": sum(hist[-3:]) / len(hist[-3:]),
                   "days_in_label_month": float(days_in(label_month)), **{d: 1.0 if d == f"group_{g}" else 0.0 for d in DUMMIES},
                   "net_trend_2m_pct": (100.0 * (hist[-1] - base2) / base2) if base2 else None,
                   "ads_to_gross_lag1": _ratio(cur.get("ads_cost"), cur.get("gross_reference_sales")),
                   "campaign_discount_to_gross_lag1": _ratio(cur.get("campaign_reduction"), cur.get("gross_reference_sales")),
                   "voucher_to_gross_lag1": _ratio(cur.get("voucher_discount"), cur.get("gross_reference_sales")),
                   "affiliate_to_gross_lag1": _ratio(cur.get("affiliate_cost"), cur.get("gross_reference_sales")),
                   "label_net": net[g][i + 1] if i + 1 < len(months) else None, "is_inference": i + 1 == len(months)}
            table.append(row)
    return {"months": months, "cutoff": cutoff, "table": table}


def feature_stats(table: list[dict]) -> dict:
    """Mean / std / min / max / missing share per numeric feature over the labelled training rows (used later for drift checks)."""
    stats = {}
    names = [f["name"] for f in FEATURES if f["type"] != "indicator"]
    train = [r for r in table if not r["is_inference"]]
    for name in names:
        vals = [r[name] for r in train if r[name] is not None]
        n_all = len(train)
        if vals:
            mean = sum(vals) / len(vals)
            std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
            stats[name] = {"n": len(vals), "missing_share": round(1 - len(vals) / n_all, 4), "mean": mean, "std": std, "min": min(vals), "max": max(vals)}
        else:
            stats[name] = {"n": 0, "missing_share": 1.0, "mean": None, "std": None, "min": None, "max": None}
    return stats
