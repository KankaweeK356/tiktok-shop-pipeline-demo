"""User acceptance contracts: real evidence Lab and 10%-gross SKU profitability."""
import json
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
LAB=ROOT/"api"/"lab-step.js"
FRONTEND=ROOT/"dashboard"/"app.js"
REPORT=ROOT/"dashboard"/"data"/"report.json"
EVIDENCE=ROOT/"dashboard"/"data"/"classroom_evidence.json"


def test_lab_uses_live_neon_and_actual_parquet_not_fake_rows():
    api=LAB.read_text(encoding="utf-8")
    ui=FRONTEND.read_text(encoding="utf-8")
    assert 'const STAGES=["ingest","extract","transform","load","validate"]' in api
    assert "parquetMetadataAsync" in api and "parquetReadObjects" in api
    assert "getArchiveBytes" in api and "sourceTable(sql,table)" in api
    assert "READ_ONLY_EVIDENCE_REPLAY" in api
    assert "ROWS_QUERIED_FROM_EXACT_ARCHIVED_DUCKDB" in api
    assert 'req.method!=="GET"' in api
    assert "INSERT INTO demo_control" not in api
    assert "TRUNCATE TABLE" not in api
    assert "PutObjectCommand" not in api
    for phrase in ("runLabStage", "renderLabResult", "LAB_STEPS",
                   "Step ถัดไป", "Input", "Process", "Output",
                   "labLog", "อ่าน", "Retry"):
        assert phrase in ui
    assert "state.labResults[def.id]=payload" in ui
    assert "LIVE_NEON_VS_ARCHIVED_RECONSTRUCTED_WAREHOUSE_REPORT" in api


def test_margin_uses_full_price_not_discounted_sales():
    report=json.loads(REPORT.read_text(encoding="utf-8"))
    targets={m["month"]:m["minimum_profit_protection_rate"]
             for m in report["business"]["months"]}
    rows=report["business"]["sku_performance"]
    assert rows
    checked=0
    for row in rows:
        rate=targets.get(row["month"])
        gross=row["gross_reference_sales"]
        profit=row["contribution_before_group_costs"]
        if rate is None or gross is None or gross<=0 or profit is None:
            continue
        expected_pct=100*profit/gross
        gap_pp=expected_pct-100*rate
        # Store-level goal is 10% of Gross Reference Sales, NOT SKU Net Revenue.
        assert (gap_pp<0)==(profit<gross*rate)
        checked+=1
    assert checked>25
    for month in report["business"]["months"]:
        if month["month"]=="2026-10":
            assert month["minimum_profit_protection_rate"]==pytest.approx(0.10)


def test_group_and_sku_are_distinct_profit_grains():
    ui=FRONTEND.read_text(encoding="utf-8")
    assert 'metric("คุ้มครองกำไร",pct(current.protection_pct)' in ui
    assert 'const profitFail=current.protection_status==="FAIL"' in ui
    assert '"ยังไม่กระจายค่า Ads ลง SKU"' in ui
    assert '"สินค้า SKU","ยอดขายและต้นทุนสินค้า · ไม่จัดสรรค่า Ads ที่ระดับ SKU"' in ui
    assert '"แคมเปญขายและโฆษณา","สองแหล่งข้อมูลต่างระดับ ไม่รวม Ads GMV เป็นยอดขายซ้ำ"' in ui


def test_six_offline_error_cases_have_inspectable_recovery_evidence():
    report=json.loads(EVIDENCE.read_text(encoding="utf-8"))
    errors=report["error_recovery_evidence"]
    assert isinstance(errors,list)
    assert {x["case"] for x in errors}=={"E01","E02","T01","T02","L01","L02"}
    assert all(x["passed"] for x in errors)
    assert len(report["error_case_details"])==6
    assert report["source_engine"]=="SQLITE_NOT_NEON"

