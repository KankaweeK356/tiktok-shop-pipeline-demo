"""Export an inspectable, static Decision Dashboard payload from real demo outputs.

NO hardcoded scores or invented business KPIs. The same SQL view, Mart, ML files,
Functional Reconciliation, and Serving Replay shown in the classroom are the source.
Use the JSON as a frozen batch snapshot on a static Vercel/GitHub Pages frontend.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd


SCHEMA_VERSION = "decision_dashboard_v1"


def _csv_records(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"Required evaluated report is absent: {path}")
    return json.loads(pd.read_csv(path).to_json(orient="records", force_ascii=False))


def _query_records(con, query: str) -> list[dict]:
    return json.loads(con.execute(query).df().to_json(orient="records", force_ascii=False))


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Required pipeline/ML evidence absent: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _check_money(a, b, name, tol=0.02):
    if abs(float(a) - float(b)) > tol:
        raise AssertionError(f"{name}: source mismatch {a} != {b}")


def export_dashboard(
    warehouse_path: str | Path,
    report_dir: str | Path,
    source_dir: str | Path,
    output_file: str | Path,
) -> dict:
    warehouse_path = Path(warehouse_path)
    reports = Path(report_dir)
    source = Path(source_dir)
    output = Path(output_file)
    if not warehouse_path.is_file():
        raise FileNotFoundError("Historical DuckDB warehouse required")

    ml = reports / "ml_weekly"
    hist_summary = _read_json(reports / "ml_history_summary.json")
    ml_summary = _read_json(ml / "weekly_backtest_summary.json")
    monitor = _read_json(ml / "serving_monitor_replay.json")
    registry = _read_json(ml / "weekly_model_registry.json")
    functional_initial = _read_json(reports / "functional_initial.json")
    functional_incremental = _read_json(reports / "functional_incremental.json")

    if ml_summary["data"] != "SYNTHETIC_EDUCATIONAL_NOT_TIKTOK":
        raise AssertionError("Wrong data classification")
    if ml_summary["model_use"] != "DEMO_ONLY_NOT_PRODUCTION":
        raise AssertionError("Unsupported ML approval")
    if ml_summary["fidelity"] != "RETROSPECTIVE_LATEST_DWH":
        raise AssertionError("Do not promote historical snapshot as point-in-time verified")
    if registry["selected_model"] != ml_summary["selected_by_validation"]:
        raise AssertionError("Model registry and evaluated selection disagree")
    if monitor["selected_model"] != registry["selected_model"]:
        raise AssertionError("Serving replay is not aligned to model registry")
    if functional_incremental["failed"] or functional_initial["failed"]:
        raise AssertionError("Do not publish failed ETL reconciliation as successful")

    con = duckdb.connect(str(warehouse_path), read_only=True)
    try:
        months = _query_records(con, '''
            SELECT "Year_Month" AS month,
                   "Gross_Reference_Sales" AS gross_reference_sales,
                   "Net_Revenue" AS net_revenue,
                   "Contribution_Profit" AS contribution_profit,
                   "Revenue_Target" AS revenue_target,
                   "Revenue_Achievement_Pct" AS revenue_achievement_pct,
                   "Profit_Protection_Rate_Pct" AS profit_protection_rate_pct,
                   "Minimum_Profit_Protection_Rate" AS minimum_profit_protection_rate,
                   "Profit_Protection_Status" AS profit_protection_status,
                   "Profit_Data_Status" AS profit_data_status,
                   "Target_Status" AS target_status
              FROM "View_Shop_Monthly_KPI" ORDER BY "Year_Month"
        ''')
        groups = _query_records(con, '''
            SELECT d."Year_Month" AS month,
                   m."Product_Group_ID" AS product_group_id,
                   MAX(m."Product_Group_Name") AS product_group_name,
                   SUM(m."Gross_Reference_Sales") AS gross_reference_sales,
                   SUM(m."Net_Revenue") AS net_revenue,
                   SUM(m."Ads_Cost") AS ads_cost,
                   SUM(m."Campaign_Price_Reduction") AS campaign_reduction,
                   CASE WHEN SUM(CASE WHEN m."Contribution_Profit" IS NULL
                                      THEN 1 ELSE 0 END)>0 THEN NULL
                        ELSE SUM(m."Contribution_Profit") END AS contribution_profit
              FROM "Mart_Product_Group_Daily_Performance" m
              JOIN "Dim_Date" d ON m."Date_Key" = d."Date_Key"
             GROUP BY 1,2 ORDER BY 1,2
        ''')
        sku_performance = _query_records(con, '''
            SELECT d."Year_Month" AS month,
                   p."Product_Group_ID" AS product_group_id,
                   p."SKU_ID" AS sku_id,
                   MAX(p."SKU_Name") AS sku_name,
                   MAX(p."Color") AS color,
                   MAX(p."Size") AS size,
                   SUM(s."Quantity") AS quantity,
                   SUM(s."Gross_Reference_Sales") AS gross_reference_sales,
                   SUM(s."Campaign_Price_Reduction") AS campaign_reduction,
                   SUM(s."Voucher_Allocated") AS voucher_discount,
                   SUM(s."Net_Revenue") AS net_revenue,
                   SUM(s."COGS") AS cogs,
                   SUM(s."Platform_Fee_Cost") AS platform_cost,
                   SUM(s."Fulfillment_Cost") AS fulfillment_cost,
                   SUM(s."Affiliate_Cost") AS affiliate_cost,
                   SUM(s."Sales_Contribution_Pre_Ads_Sample_Claim")
                       AS contribution_before_group_costs
              FROM "Fact_Sales_Order_Item" s
              JOIN "Dim_Product" p ON s."Product_Key"=p."Product_Key"
              JOIN "Dim_Date" d ON s."Sales_Date_Key"=d."Date_Key"
             GROUP BY 1,2,3 ORDER BY 1,2,3
        ''')
        ads_campaigns = _query_records(con, '''
            SELECT d."Year_Month" AS month,
                   f."Product_Group_ID" AS product_group_id,
                   f."Ad_Campaign_Key" AS ad_campaign_key,
                   SUM(f."Ads_Spend") AS ads_spend,
                   SUM(f."Impressions") AS impressions,
                   SUM(f."Clicks") AS clicks,
                   SUM(f."Conversions") AS conversions
              FROM "Fact_Ads_Daily" f
              JOIN "Dim_Date" d ON f."Date_Key"=d."Date_Key"
             GROUP BY 1,2,3 ORDER BY 1,2,3
        ''')
        creator_performance = _query_records(con, '''
            SELECT d."Year_Month" AS month,
                   p."Product_Group_ID" AS product_group_id,
                   s."Creator_Key" AS creator_key,
                   SUM(s."Net_Revenue") AS associated_sales,
                   SUM(s."Affiliate_Cost") AS affiliate_commission,
                   SUM(s."Quantity") AS units
              FROM "Fact_Sales_Order_Item" s
              JOIN "Dim_Product" p ON s."Product_Key"=p."Product_Key"
              JOIN "Dim_Date" d ON s."Sales_Date_Key"=d."Date_Key"
             WHERE s."Affiliate_Cost">0
             GROUP BY 1,2,3 ORDER BY 1,2,3
        ''')
        tables = _query_records(con, '''
            SELECT table_name, COUNT(*) OVER() AS physical_tables
              FROM information_schema.tables
             WHERE table_schema='main' AND table_type='BASE TABLE'
             ORDER BY table_name
        ''')
        fact_sales_count = con.execute(
            'SELECT COUNT(*) FROM "Fact_Sales_Order_Item"'
        ).fetchone()[0]
        ads_cost = con.execute(
            'SELECT COALESCE(SUM("Ads_Spend"),0) FROM "Fact_Ads_Daily"'
        ).fetchone()[0]
        mart_ads_cost = con.execute(
            'SELECT COALESCE(SUM("Ads_Cost"),0) FROM "Mart_Product_Group_Daily_Performance"'
        ).fetchone()[0]
    finally:
        con.close()

    if not months or not groups:
        raise AssertionError("No business data after ETL")
    for month in months:
        g = [x for x in groups if x["month"] == month["month"]]
        _check_money(sum(float(v["net_revenue"]) for v in g),
                     month["net_revenue"], f"Monthly Net Revenue {month['month']}")
        if month["profit_data_status"] == "COMPLETE":
            _check_money(sum(float(v["contribution_profit"]) for v in g),
                         month["contribution_profit"], f"Monthly Profit {month['month']}")
        if month["revenue_target"] and month["target_status"] == "OK":
            _check_money(100 * float(month["net_revenue"]) /
                         float(month["revenue_target"]),
                         month["revenue_achievement_pct"],
                         f"Target Achievement {month['month']}", tol=0.011)
        if month["profit_data_status"] == "COMPLETE" and month["gross_reference_sales"]:
            _check_money(100 * float(month["contribution_profit"]) /
                         float(month["gross_reference_sales"]),
                         month["profit_protection_rate_pct"],
                         f"Profit Protection {month['month']}", tol=0.011)
    for month in months:
        for group in [g for g in groups if g["month"] == month["month"]]:
            sku_rows = [
                x for x in sku_performance
                if x["month"] == month["month"] and
                x["product_group_id"] == group["product_group_id"]
            ]
            _check_money(sum(float(x["net_revenue"]) for x in sku_rows),
                         group["net_revenue"],
                         f"SKU drilldown reconciliation {month['month']}/{group['product_group_id']}")
    _check_money(sum(float(x["ads_spend"]) for x in ads_campaigns),
                 ads_cost, "Ads campaign subtotal vs source Fact")
    _check_money(ads_cost, mart_ads_cost, "Ads Fact vs Mart")
    _check_money(fact_sales_count, functional_incremental["warehouse_sales_item_count"],
                 "Sales count")

    checkpoint_dir = warehouse_path.parent / "lake" / "control"
    stages = []
    for batch in ("initial", "incremental"):
        checkpoint = _read_json(checkpoint_dir / f"checkpoint_{batch}.json")
        for stage in ("ingest", "extract", "transform", "load", "validate"):
            record = checkpoint["metrics"].get(stage)
            stages.append({
                "batch": batch,
                "stage": stage,
                "status": "SUCCESS" if stage in checkpoint["completed"] else "NOT_RUN",
                "elapsed_seconds": record.get("elapsed_seconds") if record else None,
                "summary": record.get("result") if record else None,
            })
    lineage_path = reports / "lineage_incremental.csv"
    lineage = _csv_records(lineage_path)[:8] if lineage_path.is_file() else []

    select = _csv_records(ml / "weekly_model_selection.csv")
    scores = _csv_records(ml / "weekly_test_metrics.csv")
    test_by_group = _csv_records(ml / "weekly_test_by_group.csv")
    test_predictions = _csv_records(ml / "weekly_test_predictions.csv")
    validation_folds = _csv_records(ml / "weekly_rolling_folds.csv")
    importance = _csv_records(ml / "weekly_feature_importance.csv")
    serving = _csv_records(ml / "serving_replay_predictions.csv")
    feature_path = ml / "weekly_training_dataset.parquet"
    if not feature_path.is_file():
        raise FileNotFoundError("Training data Parquet missing")
    feature_frame = pd.read_parquet(feature_path)
    example_features = json.loads(
        feature_frame[[
            "as_of_date", "forecast_week_start", "product_group_id",
            "revenue_last_week", "revenue_mean_4weeks",
            "historical_ads_last_week", "planned_ads_week",
            "planned_discount_mean_week", "actual_net_revenue_week",
            "history_fidelity",
        ]].head(10).to_json(orient="records", force_ascii=False)
    )
    if len(test_predictions) != 3 * 8 * 5:
        raise AssertionError("Not all models/weeks/groups have predictions")
    if not scores or len(select) != 3:
        raise AssertionError("Incomplete ML metrics")

    # Not all source data should be sent to a public static site:
    # only synthetic aggregates and a tiny lineage preview are exported.
    plan_df = pd.read_csv(source / "ml_marketing_plan.csv")
    planned_week = monitor["forecast_week"]
    week_end = (
        pd.Timestamp(planned_week) + pd.Timedelta(days=6)
    ).strftime("%Y-%m-%d")
    plan_slice = plan_df.loc[
        plan_df["plan_date"].between(planned_week, week_end)
    ].groupby("product_group_id", as_index=False).agg(
        planned_ads_week=("planned_ads_spend", "sum"),
        planned_discount_mean_week=("planned_campaign_discount_rate", "mean"),
    )
    plan_reference = json.loads(
        plan_slice.to_json(orient="records", force_ascii=False)
    )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_classification": "SYNTHETIC_EDUCATIONAL_NOT_TIKTOK",
        "snapshot_mode": "BATCH_SNAPSHOT_NOT_LIVE",
        "source_run": "ml_history_ci__incremental__weekly_mlops_demo",
        "links": {
            "repo": "https://github.com/KankaweeK356/tiktok-shop-pipeline-demo",
            "pipeline": "https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/actions/workflows/ml-history-ci.yml",
            "ml": "https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/actions/workflows/ml-weekly-demo-ci.yml",
            "schema": "https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/blob/main/schemas/ER2_V5.dbml",
            "ml_guide": "https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/blob/main/docs/ML_WEEKLY_DEMO_GUIDE_TH.md",
        },
        "pipeline": {
            "history": hist_summary,
            "initial": functional_initial,
            "incremental": functional_incremental,
            "stages": stages,
            "lineage_sample": lineage,
            "physical_warehouse_tables": len(tables),
            "physical_warehouse_table_names": [r["table_name"] for r in tables],
            "ads_fact_to_mart_difference": round(float(ads_cost - mart_ads_cost), 3),
            "error_recovery_in_history_run": "NOT_EXECUTED_IN_THIS_RUN",
        },
        "business": {
            "months": months,
            "groups": groups,
            "sku_performance": sku_performance,
            "ads_campaigns": ads_campaigns,
            "creator_performance": creator_performance,
            "shop_profit_protection_basis": "CONTRIBUTION_PROFIT_DIVIDED_BY_GROSS_REFERENCE_SALES",
            "revenue_target_basis": "MONTHLY_NET_REVENUE_DIVIDED_BY_REVENUE_TARGET",
        },
        "ml": {
            "backtest": ml_summary,
            "registry": registry,
            "monitoring": monitor,
            "model_selection": select,
            "test_metrics": scores,
            "test_by_group": test_by_group,
            "test_predictions": test_predictions,
            "validation_folds": validation_folds,
            "feature_importance": importance,
            "feature_count": int(len(feature_frame)),
            "feature_preview": example_features,
            "serving_predictions": serving,
        },
        "scenario": {
            "mode": "PLANNING_INPUT_ONLY_NO_COUNTERFACTUAL_FORECAST",
            "reference_week": planned_week,
            "reference_plans": plan_reference,
            "ads_budget_control": "PRODUCT_GROUP_WEEK",
            "discount_control": "PRODUCT_GROUP_WEEK",
            "warning": (
                "Changing a plan in this static demo does NOT calculate sales uplift, "
                "Contribution Profit or a causal prediction."
            ),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return payload


def main():
    parser = argparse.ArgumentParser(description="Export source-backed demo dashboard JSON")
    parser.add_argument("--warehouse", default="output/ml_history_ci/main/er2.duckdb")
    parser.add_argument("--reports", default="output/ml_history_ci/main/reports")
    parser.add_argument("--source", default="output/ml_history_ci/source")
    parser.add_argument("--output", default="dashboard/data/report.json")
    args = parser.parse_args()
    report = export_dashboard(args.warehouse, args.reports, args.source, args.output)
    print(json.dumps({
        "status": "EXPORTED",
        "file": args.output,
        "months": len(report["business"]["months"]),
        "group_months": len(report["business"]["groups"]),
        "trained_models": len(report["ml"]["test_metrics"]),
        "prediction_rows": len(report["ml"]["test_predictions"]),
        "stage_rows": len(report["pipeline"]["stages"]),
        "business_data_origin": "DuckDB_Monthly_KPI_VIEW_AND_GROUP_MART",
        "accuracy_origin": "ML_WEEKLY_BACKTEST_CSV",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
