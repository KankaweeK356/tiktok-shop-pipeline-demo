"""Build full synthetic ML-history dataset and verify it across the unchanged ETL flow."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from .generate_ml_history import generate_ml_history, SCENARIO_ID
from .ml_features import read_warehouse_daily, build_feature_rows
from .orchestrator import run_batch


def main() -> None:
    out = Path("output/ml_history_ci")
    source = out / "source"
    workspace = out / "main"
    generated = generate_ml_history(source, seed=8102)
    initial = run_batch(workspace, "initial", source)
    if initial["status"] != "SUCCESS" or initial["functional_fails"]:
        raise AssertionError("Historical initial load / validation failed")
    incremental = run_batch(workspace, "incremental", source)
    if incremental["status"] != "SUCCESS" or incremental["functional_fails"]:
        raise AssertionError("Historical incremental load / validation failed")
    replay = run_batch(workspace, "incremental", source)
    if replay["net_revenue"] != incremental["net_revenue"]:
        raise AssertionError("Incremental replay changed revenue")

    dw = duckdb.connect(str(workspace / "er2.duckdb"), read_only=True)
    try:
        month_df = dw.execute('''SELECT "Year_Month", "Net_Revenue",
                               "Gross_Reference_Sales", "Contribution_Profit",
                               "Profit_Protection_Status"
                               FROM "View_Shop_Monthly_KPI"
                               ORDER BY "Year_Month"''').df()
        group_df = dw.execute('''SELECT d."Year_Month",
                               m."Product_Group_ID", SUM(m."Net_Revenue") AS net_revenue,
                               SUM(m."Ads_Cost") AS ads_cost,
                               SUM(m."Campaign_Price_Reduction") AS campaign_reduction
                               FROM "Mart_Product_Group_Daily_Performance" m
                               JOIN "Dim_Date" d ON m."Date_Key"=d."Date_Key"
                               GROUP BY 1,2 ORDER BY 1,2''').df()
        ads_count = dw.execute('''SELECT COUNT(*) FROM "Fact_Ads_Daily"
            WHERE "Date_Key" BETWEEN 20251101 AND 20260930''').fetchone()[0]
        source_ads_sum = float(dw.execute(
            'SELECT SUM("Ads_Spend") FROM "Fact_Ads_Daily"').fetchone()[0])
        mart_ads_sum = float(dw.execute(
            'SELECT SUM("Ads_Cost") FROM "Mart_Product_Group_Daily_Performance"'
        ).fetchone()[0])
        dim_date_min_max = dw.execute(
            'SELECT MIN("Full_Date"),MAX("Full_Date") FROM "Dim_Date"'
        ).fetchone()
    finally:
        dw.close()
    assert len(month_df) == 13, f"Expected 12 historical+October months and 1 incremental: {len(month_df)}"
    assert month_df["Year_Month"].iloc[0] == "2025-11"
    assert month_df["Year_Month"].iloc[-1] == "2026-11"
    assert len(group_df) >= 12 * 5
    assert ads_count == generated["historical_ads_rows"]
    assert abs(source_ads_sum - mart_ads_sum) < 0.02
    assert str(dim_date_min_max[0]) <= "2025-11-01"

    daily = read_warehouse_daily(workspace / "er2.duckdb")
    plans = pd.read_csv(source / "ml_marketing_plan.csv")
    feature = build_feature_rows(
        daily, plans, as_of_date="2026-09-28", horizon_days=2,
        scenario_id=SCENARIO_ID, source_run_id="mlhistory-initial",
    )
    assert len(feature) == 10
    assert feature["feature_status"].eq("READY").all(), feature["feature_status"].tolist()
    assert feature["target_net_revenue"].notna().all()
    assert not feature["training_ready"].any()
    reports = workspace / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    month_df.to_csv(reports / "ml_history_monthly_kpi.csv", index=False)
    group_df.to_csv(reports / "ml_history_group_monthly.csv", index=False)
    feature.to_csv(reports / "ml_history_feature_preview.csv", index=False)
    summary = {
        "source": generated,
        "initial_pipeline": {
            "status": initial["status"],
            "functional_fails": initial["functional_fails"],
            "paid_item_rows": initial["paid_sales_rows"]
        },
        "incremental_pipeline": {
            "status": incremental["status"],
            "functional_fails": incremental["functional_fails"],
            "paid_item_rows": incremental["paid_sales_rows"]
        },
        "months": len(month_df),
        "product_group_month_rows": len(group_df),
        "historical_ad_fact_rows": ads_count,
        "ads_reconciliation_difference": round(source_ads_sum - mart_ads_sum, 3),
        "feature_preview_rows": len(feature),
        "feature_preview_training_ready": False,
        "data_classification": "SYNTHETIC_EDUCATIONAL_NOT_TIKTOK",
    }
    (reports / "ml_history_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
