"""Feature definitions (the contract of the Feature Store) and model definitions. Versioned: change => new FEATURE_VERSION."""
from __future__ import annotations

GROUPS = ("PG01", "PG02", "PG03", "PG04", "PG05")
FEATURE_VERSION = "mlops-features-1"
DEFAULT_PREFIX = "vercel-lab/ml"
FORBIDDEN_TOKENS = ("scenario", "expected", "qa_", "target_month_actual", "golden", "plan_")

_KNOWN = "end of the origin month (published before the label month starts)"
FEATURES = [
    {"name": "lag1_group_net", "type": "number", "description": "Net revenue of the group in the origin month",
     "formula": "SUM(Net_Revenue) of the origin month", "source": "Mart_Product_Group_Daily_Performance.Net_Revenue", "known_at": _KNOWN,
     "used_in": ["ridge_base", "ridge_marketing"]},
    {"name": "trailing3_group_net_mean", "type": "number", "description": "Mean group net revenue of the last 3 months up to the origin month",
     "formula": "mean(net[origin-2 .. origin])", "source": "Mart_Product_Group_Daily_Performance.Net_Revenue", "known_at": _KNOWN,
     "used_in": ["ridge_base", "ridge_marketing"]},
    {"name": "days_in_label_month", "type": "number", "description": "Calendar days of the month being predicted (a calendar fact, not data)",
     "formula": "days(label_month)", "source": "calendar", "known_at": "always known", "used_in": ["ridge_base", "ridge_marketing"]},
    *[{"name": f"group_{g}", "type": "indicator", "description": f"One-hot indicator of product group {g}", "formula": f"1 if group == {g} else 0",
       "source": "Dim_Product_Group", "known_at": "always known", "used_in": ["ridge_base", "ridge_marketing"]} for g in GROUPS],
    {"name": "net_trend_2m_pct", "type": "number", "description": "Net revenue growth over the last two months up to the origin month (null when the base is 0)",
     "formula": "(net[origin] - net[origin-2]) / net[origin-2] * 100", "source": "Mart_Product_Group_Daily_Performance.Net_Revenue", "known_at": _KNOWN,
     "used_in": []},
    {"name": "ads_to_gross_lag1", "type": "ratio", "description": "Ads cost of the origin month divided by Gross Reference Sales of the same month",
     "formula": "SUM(Ads_Cost) / SUM(Gross_Reference_Sales)", "source": "Mart_Product_Group_Daily_Performance.Ads_Cost / Gross_Reference_Sales",
     "known_at": _KNOWN, "used_in": ["ridge_marketing"]},
    {"name": "campaign_discount_to_gross_lag1", "type": "ratio", "description": "Campaign price reduction of the origin month divided by Gross Reference Sales of the same month",
     "formula": "SUM(Campaign_Price_Reduction) / SUM(Gross_Reference_Sales)", "source": "Mart_Product_Group_Daily_Performance.Campaign_Price_Reduction / Gross_Reference_Sales",
     "known_at": _KNOWN, "used_in": ["ridge_marketing"]},
    {"name": "voucher_to_gross_lag1", "type": "ratio", "description": "DEFINED FOR FUTURE EXPERIMENTS (not used in any model yet)",
     "formula": "SUM(Voucher_Discount) / SUM(Gross_Reference_Sales)", "source": "Mart_Product_Group_Daily_Performance.Voucher_Discount", "known_at": _KNOWN, "used_in": []},
    {"name": "affiliate_to_gross_lag1", "type": "ratio", "description": "DEFINED FOR FUTURE EXPERIMENTS (not used in any model yet)",
     "formula": "SUM(Affiliate_Cost) / SUM(Gross_Reference_Sales)", "source": "Mart_Product_Group_Daily_Performance.Affiliate_Cost", "known_at": _KNOWN, "used_in": []},
]
NUMERIC_BASE = ["lag1_group_net", "trailing3_group_net_mean", "days_in_label_month"]
DUMMIES = [f"group_{g}" for g in GROUPS]
MARKETING = ["ads_to_gross_lag1", "campaign_discount_to_gross_lag1"]

MODEL_VERSIONS = {"baseline_trailing_3_month_mean": "baseline-trailing3-1", "baseline_naive_previous_month": "baseline-naive-1",
                  "ridge_base": "mlops-ridge-1", "ridge_marketing": "mlops-ridge-marketing-1"}
MODELS = {
    "baseline_trailing_3_month_mean": {"kind": "baseline", "features": [], "description": "Mean of the last 3 months per group (the official baseline)"},
    "baseline_naive_previous_month": {"kind": "baseline", "features": [], "description": "Previous month per group"},
    "ridge_base": {"kind": "ridge", "numeric": NUMERIC_BASE, "dummies": DUMMIES, "official_candidate": True,
                   "description": "Pooled ridge with the features of the official ML challenger (same maths as monthly_forecast)"},
    "ridge_marketing": {"kind": "ridge", "numeric": NUMERIC_BASE + MARKETING, "dummies": DUMMIES, "official_candidate": False,
                        "description": "EXPERIMENTAL challenger: ridge_base + prior-month marketing ratios. Never enters official model selection."},
}
