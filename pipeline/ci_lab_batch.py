"""Run all five genuine classroom stages in one GitHub Actions worker."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
import duckdb

from .ci_lab_stage import STATE_PATH, run_stage
from .orchestrator import STAGES
from .generate_classroom_source import BATCHES
from .ml_weekly import weekly_readiness

ROOT = Path(__file__).resolve().parents[1]


def run_stage_and_save(batch: str, stage: str) -> dict:
    if batch not in BATCHES and batch != "incremental_02_error":
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
    if batch != "initial":
        prior_batch = BATCHES[BATCHES.index(batch)-1]
        initial = json.loads((workspace / "batch_results" / prior_batch / "ingest.json")
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
        def rows(query: str) -> list[dict]:
            return json.loads(db.execute(query).df().to_json(orient="records",date_format="iso"))
        summary["business"] = {
            "months": rows('''SELECT Year_Month AS month, Gross_Reference_Sales AS gross,
                Net_Revenue AS net, Contribution_Profit AS profit,
                Revenue_Target AS target, Revenue_Gap AS gap,
                Revenue_Achievement_Pct AS achievement_pct,
                Profit_Protection_Rate_Pct AS protection_pct,
                Profit_Protection_Status AS protection_status,
                Profit_Data_Status AS profit_data_status,Target_Status AS target_status
                FROM View_Shop_Monthly_KPI ORDER BY Year_Month'''),
            "groups": rows('''SELECT d.Year_Month AS month,m.Product_Group_ID AS group_id,
                MAX(m.Product_Group_Name) AS group_name,
                SUM(m.Net_Revenue) AS net,SUM(m.Gross_Reference_Sales) AS gross,
                CASE WHEN COUNT(*)=COUNT(m.Contribution_Profit)
                     THEN SUM(m.Contribution_Profit) ELSE NULL END AS profit,
                SUM(m.Ads_Cost) AS ads_cost,SUM(m.Campaign_Price_Reduction) AS campaign_reduction,
                SUM(m.Voucher_Discount) AS voucher_discount
                FROM Mart_Product_Group_Daily_Performance m
                JOIN Dim_Date d ON d.Date_Key=m.Date_Key GROUP BY 1,2 ORDER BY 1,2'''),
            "days": rows('''SELECT d.Year_Month AS month,d.Full_Date AS day,
                m.Product_Group_ID AS group_id,m.Net_Revenue AS net,
                m.Gross_Reference_Sales AS gross,m.Contribution_Profit AS profit,
                m.Ads_Cost AS ads_cost,m.Data_Cost_Basis AS cost_basis
                FROM Mart_Product_Group_Daily_Performance m
                JOIN Dim_Date d ON d.Date_Key=m.Date_Key ORDER BY 1,2,3'''),
            "sku": rows('''SELECT d.Year_Month AS month,p.Product_Group_ID AS group_id,
                p.SKU_ID AS sku_id,p.SKU_Name AS sku_name,
                COUNT(*) AS paid_items,SUM(s.Net_Revenue) AS net,
                SUM(s.Gross_Reference_Sales) AS gross,SUM(s.COGS) AS cogs
                FROM Fact_Sales_Order_Item s
                JOIN Dim_Product p ON p.Product_Key=s.Product_Key
                JOIN Dim_Date d ON d.Date_Key=s.Sales_Date_Key
                GROUP BY 1,2,3,4 ORDER BY 1,2,3'''),
            "campaigns": rows('''SELECT d.Year_Month AS month,s.Campaign_ID AS campaign_id,
                MAX(s.Campaign_Name) AS campaign_name,COUNT(*) AS paid_items,
                SUM(s.Net_Revenue) AS net,SUM(s.Campaign_Price_Reduction) AS price_reduction
                FROM Fact_Sales_Order_Item s JOIN Dim_Date d ON d.Date_Key=s.Sales_Date_Key
                WHERE s.Campaign_ID IS NOT NULL GROUP BY 1,2 ORDER BY 1,2'''),
            "ad_campaigns": rows('''SELECT d.Year_Month AS month,a.Product_Group_ID AS group_id,
                c.Ad_Campaign_ID AS campaign_id,c.Ad_Campaign_Name AS campaign_name,
                SUM(a.Ads_Spend) AS ads_cost,SUM(a.Impressions) AS impressions,
                SUM(a.Clicks) AS clicks
                FROM Fact_Ads_Daily a JOIN Dim_Date d ON d.Date_Key=a.Date_Key
                JOIN Dim_Ad_Campaign c ON c.Ad_Campaign_Key=a.Ad_Campaign_Key
                GROUP BY 1,2,3,4 ORDER BY 1,2,3'''),
        }
    summary["no_duplicate_sales_items"] = total == distinct
    if not summary["no_duplicate_sales_items"]:
        raise RuntimeError("Warehouse contains duplicate sales item IDs")
    plan = Path(os.getenv("CLASSROOM_ML_PLAN", str(
        ROOT / "pipeline" / "assets" / "classroom_ml_marketing_plan.csv")))
    if plan.is_file():
        summary["ml_readiness"] = weekly_readiness(workspace / "er2.duckdb", plan)
    else:
        summary["ml_readiness"] = {
            "status": "INSUFFICIENT_DATA", "complete_weeks": 0,
            "minimum_weeks": 16,
            "reason": "ยังไม่มีแผนการตลาดรายสัปดาห์สำหรับประเมินความพร้อม ML"
        }
    (workspace / "batch_result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", choices=BATCHES, required=True)
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
