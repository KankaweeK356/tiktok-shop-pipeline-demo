"""Confirm Dashboard JSON truthfully reflects finance, ETL and ML evidence.

Run after:
    python -m pipeline.ci_ml_history
    python -m pipeline.ci_ml_weekly_demo
    python -m pipeline.export_dashboard
"""
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "dashboard" / "data" / "report.json"


@pytest.fixture(scope="module")
def report():
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_actual_source_and_snapshot_contract(report):
    assert report["schema_version"] == "decision_dashboard_v1"
    assert report["source_classification"] == "SYNTHETIC_EDUCATIONAL_NOT_TIKTOK"
    assert report["snapshot_mode"] == "BATCH_SNAPSHOT_NOT_LIVE"
    assert report["source_run"]
    assert report["links"]["schema"].startswith("https://github.com/")
    assert len(report["business"]["months"]) == 13
    assert len(report["business"]["groups"]) == 13 * 5


def test_monthly_kpi_math_and_no_group_gate(report):
    months = report["business"]["months"]
    group_rows = report["business"]["groups"]
    for month in months:
        relevant = [g for g in group_rows if g["month"] == month["month"]]
        assert len(relevant) == 5
        assert sum(g["net_revenue"] for g in relevant) == pytest.approx(
            month["net_revenue"], abs=.02
        )
        if month["target_status"] == "OK":
            assert month["revenue_achievement_pct"] == pytest.approx(
                100 * month["net_revenue"] / month["revenue_target"], abs=.011
            )
        if month["profit_data_status"] == "COMPLETE":
            assert month["contribution_profit"] is not None
            assert month["profit_protection_rate_pct"] == pytest.approx(
                100 * month["contribution_profit"] /
                month["gross_reference_sales"], abs=.011
            )
            assert month["profit_protection_status"] in ("PASS", "FAIL")
    assert report["business"]["shop_profit_protection_basis"] == (
        "CONTRIBUTION_PROFIT_DIVIDED_BY_GROSS_REFERENCE_SALES"
    )
    assert report["business"]["revenue_target_basis"] == (
        "MONTHLY_NET_REVENUE_DIVIDED_BY_REVENUE_TARGET"
    )
    # Group x month source data has NO independent shop-level approval field.
    assert all("profit_protection_status" not in x for x in group_rows)


def test_pipeline_validation_is_source_backed(report):
    pipeline = report["pipeline"]
    assert pipeline["initial"]["failed"] == 0
    assert pipeline["incremental"]["failed"] == 0
    assert pipeline["physical_warehouse_tables"] == 11
    assert len(pipeline["stages"]) == 10
    assert all(x["status"] == "SUCCESS" for x in pipeline["stages"])
    assert pipeline["incremental"]["source_paid_item_count"] == (
        pipeline["incremental"]["warehouse_sales_item_count"]
    )
    assert pipeline["incremental"]["er1_net_revenue"] == pytest.approx(
        pipeline["incremental"]["er2_net_revenue"], abs=.02
    )
    assert pipeline["ads_fact_to_mart_difference"] == pytest.approx(0, abs=.02)
    assert pipeline["error_recovery_in_history_run"] == "NOT_EXECUTED_IN_THIS_RUN"


def test_ml_backtest_metrics_and_serving_are_not_invented(report):
    ml = report["ml"]
    assert ml["backtest"]["data"] == "SYNTHETIC_EDUCATIONAL_NOT_TIKTOK"
    assert ml["backtest"]["fidelity"] == "RETROSPECTIVE_LATEST_DWH"
    assert ml["registry"]["model_approval"] == "DEMO_ONLY"
    assert ml["backtest"]["model_use"] == "DEMO_ONLY_NOT_PRODUCTION"
    assert ml["registry"]["selected_model"] == ml["backtest"]["selected_by_validation"]
    assert ml["registry"]["selected_model"] == ml["monitoring"]["selected_model"]
    assert ml["feature_count"] == ml["backtest"]["dataset_rows"]
    assert len(ml["test_metrics"]) == 3
    assert len(ml["model_selection"]) == 3
    assert len(ml["test_by_group"]) == 15
    assert len(ml["test_predictions"]) == 120  # 8 weeks x 5 groups x 3 models
    assert {x["model"] for x in ml["test_metrics"]} == {
        "Last Week Naive", "LightGBM History", "LightGBM Marketing"
    }
    assert all(x["group_wape_pct"] is not None for x in ml["test_metrics"])
    assert all(x["shop_wape_pct"] is not None for x in ml["test_metrics"])
    assert all(x["actual_net_revenue_week"] >= 0 for x in ml["test_predictions"])
    assert all(x["predicted_net_revenue_week"] >= 0 for x in ml["test_predictions"])
    assert ml["monitoring"]["production_approval"] == "NOT_APPROVED"

    archived = {
        x["product_group_id"]: x["predicted_net_revenue_week"]
        for x in ml["test_predictions"]
        if x["model"] == ml["registry"]["selected_model"] and
        x["forecast_week_start"] == ml["monitoring"]["forecast_week"]
    }
    assert len(archived) == 5
    for served in ml["serving_predictions"]:
        assert served["predicted_net_revenue_week"] == pytest.approx(
            archived[served["product_group_id"]], abs=.05
        )


def test_scenario_planning_only(report):
    scenario = report["scenario"]
    assert scenario["mode"] == "PLANNING_INPUT_ONLY_NO_COUNTERFACTUAL_FORECAST"
    assert len(scenario["reference_plans"]) == 5
    assert {x["product_group_id"] for x in scenario["reference_plans"]} == {
        "PG01", "PG02", "PG03", "PG04", "PG05"
    }
    assert all("predicted_uplift" not in x for x in scenario["reference_plans"])


def test_frontend_has_real_filters_and_no_hardcoded_accuracy():
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "dashboard" / "styles.css").read_text(encoding="utf-8")
    for element in ("monthFilter", "groupFilter", "modelFilter", "exportCurrent", "app"):
        assert 'id="' + element + '"' in html
    for word in ("renderBusiness", "renderPipeline", "renderML", "renderScenario",
                 "serving_replay", "fetch(", "report.json"):
        if word == "serving_replay":
            assert "serving_predictions" in js
        else:
            assert word in js
    assert "72.92%" not in js
    assert "34.42%" not in js
    assert "@media" in css
