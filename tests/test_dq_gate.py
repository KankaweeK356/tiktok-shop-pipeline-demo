"""Generic DQ gate, Stage 1 staging, Stage 3 defense and Source lock (offline; no Neon, no network)."""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import os
import shutil
import sqlite3
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from pipeline import dq, source_lock
from pipeline.orchestrator import run_batch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = Path(os.environ["FINAL_SOURCE_PACKAGE"]) if os.environ.get("FINAL_SOURCE_PACKAGE") else None
needs_package = pytest.mark.skipif(not (PACKAGE and (PACKAGE / "monthly_source").is_dir()),
                                   reason="FINAL_SOURCE_PACKAGE not provided (NOT_TESTED)")
SKU_RULE = "REFERENCE_EXISTS:Fact_Order_Items.SKU_ID->Dim_SKU.SKU_ID"


# ------------------------------------------------------------------ catalog / engine

def test_catalog_is_derived_from_er1_contract_not_from_a_month_or_sku():
    catalog = {r.rule_id: r for r in dq.build_catalog()}
    assert SKU_RULE in catalog
    refs = [r for r in catalog.values() if r.kind == "REFERENCE_EXISTS"]
    assert len(refs) == 21 and all(r.severity == "BLOCKING" for r in refs)
    assert {"PK_UNIQUE:Fact_Orders", "NOT_NULL:Fact_Order_Items.Order_ID"} <= set(catalog)


def test_no_scenario_specific_literals_in_runtime_code():
    forbidden = ["SKU_ERR_UNKNOWN_DEMO", "ORD-202603", "marchBlocked", "PG01-BL-M",
                 "fix_patch", "qa_only", "golden_reference", "expected_kpi"]
    runtime = ["pipeline/dq.py", "pipeline/dq_recovery.py", "pipeline/source_lock.py", "pipeline/er1.py",
               "pipeline/neon_control.py", "pipeline/ci_lab_stage.py", "api/lab-worker.py", "lib/lab-dq.js",
               "dashboard/app.js", "dashboard/pipeline-state.js", "api/lab-batch.js", "api/lab-batch-result.js"]
    for name in runtime:
        text = (ROOT / name).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{name} must not contain scenario literal {token!r}"


def _staged():
    return {
        "Dim_Product_Group": [{"Product_Group_ID": "G1"}],
        "Dim_SKU": [{"SKU_ID": "A", "Product_Group_ID": "G1"}, {"SKU_ID": "B", "Product_Group_ID": "G1"}],
        "Fact_Orders": [{"Order_ID": "O1"}, {"Order_ID": "O2"}],
        "Fact_Order_Items": [
            {"Order_Item_ID": "I1", "Order_ID": "O1", "SKU_ID": "A", "Creator_ID": None, "Campaign_ID": None},
            {"Order_Item_ID": "I2", "Order_ID": "O1", "SKU_ID": "NOPE_1", "Creator_ID": None, "Campaign_ID": None},
            {"Order_Item_ID": "I3", "Order_ID": "O2", "SKU_ID": "B", "Creator_ID": None, "Campaign_ID": None},
            {"Order_Item_ID": "I4", "Order_ID": "O2", "SKU_ID": "NOPE_2", "Creator_ID": None, "Campaign_ID": None},
        ],
    }


def test_reference_rule_checks_every_row_for_any_value_and_any_table():
    report = dq.evaluate(_staged(), batch="any_batch", stage="ingest")
    rule = next(r for r in report["results"] if r["rule_id"] == SKU_RULE)
    assert (rule["checked_rows"], rule["failed_rows"], rule["status"]) == (4, 2, "FAIL")
    assert {i["invalid_value"] for i in report["issues"] if i["rule_id"] == SKU_RULE} == {"NOPE_1", "NOPE_2"}
    assert report["summary"]["blocked"] is True
    # tables that were not delivered are NOT_CHECKED, never silently PASS
    assert next(r for r in report["results"] if r["rule_id"] == "NOT_NULL:Dim_SKU.SKU_ID")["status"] == "PASS"
    assert dq.evaluate({"Dim_SKU": []}, batch="b", stage="ingest")["summary"]["passed"] == 0


def test_parent_universe_is_existing_master_plus_batch_dimensions():
    staged = _staged()
    staged["Dim_SKU"] = []                                  # masters delivered in an earlier batch
    existing = lambda table, column: {"A", "B", "NOPE_1"} if (table, column) == ("Dim_SKU", "SKU_ID") else set()
    report = dq.evaluate(staged, batch="b", stage="ingest", existing=existing)
    assert [i["invalid_value"] for i in report["issues"] if i["rule_id"] == SKU_RULE] == ["NOPE_2"]


def test_correction_is_an_overlay_with_staleness_check_and_original_row_snapshot():
    staged = _staged()
    corr = {"correction_set_id": "x", "corrections": [
        {"table": "Fact_Order_Items", "pk": {"Order_Item_ID": "I2"}, "column": "SKU_ID",
         "original_value": "NOPE_1", "new_value": "B", "version": 1},
        {"table": "Fact_Order_Items", "pk": {"Order_Item_ID": "I4"}, "column": "SKU_ID",
         "original_value": "NOPE_2", "new_value": "STILL_BAD", "version": 1}]}
    report = dq.evaluate(staged, batch="b", stage="ingest", corrections=corr)
    assert [i["invalid_value"] for i in report["issues"] if i["rule_id"] == SKU_RULE] == ["STILL_BAD"]  # wrong fix stays blocked
    assert len(report["corrections_applied"]) == 2
    stale = {"corrections": [{"table": "Fact_Order_Items", "pk": {"Order_Item_ID": "I1"}, "column": "SKU_ID",
                              "original_value": "SOMETHING_ELSE", "new_value": "B", "version": 1}]}
    with pytest.raises(Exception) as error:
        dq.evaluate(_staged(), batch="b", stage="ingest", corrections=stale)
    assert "DQ_CORRECTION_STALE" in str(error.value)


def test_pk_duplicate_and_not_null_are_blocking():
    staged = _staged()
    staged["Fact_Orders"].append({"Order_ID": "O1"})
    staged["Fact_Order_Items"][0]["Order_ID"] = None
    report = dq.evaluate(staged, batch="b", stage="ingest")
    failed = {r["rule_id"] for r in report["results"] if r["status"] == "FAIL"}
    assert {"PK_UNIQUE:Fact_Orders", "NOT_NULL:Fact_Order_Items.Order_ID"} <= failed


# ------------------------------------------------------------------ Stage 1 / Stage 3

def _legacy_source(tmp_path: Path, bad_row: int | None = None) -> Path:
    root = tmp_path / "src"
    shutil.copytree(ROOT / "source" / "initial", root / "initial")
    if bad_row is not None:
        path = root / "initial" / "Fact_Order_Items.csv"
        rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
        rows[bad_row]["SKU_ID"] = "UNSEEN_SKU_XYZ"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
    return root


def test_stage1_gate_blocks_before_anything_reaches_er1(tmp_path):
    source = _legacy_source(tmp_path, bad_row=7)             # any row, any value
    with pytest.raises(dq.DQBlocked) as blocked:
        run_batch(tmp_path / "ws", "initial", source_root=source)
    assert blocked.value.code == "DQ_BLOCKED"
    issue = blocked.value.report["issues"][0]
    assert issue["invalid_value"] == "UNSEEN_SKU_XYZ" and issue["source_row_no"] == 8
    assert issue["row_snapshot"]["SKU_ID"] == "UNSEEN_SKU_XYZ"
    with sqlite3.connect(tmp_path / "ws" / "er1.sqlite") as db:    # nothing was promoted
        assert db.execute("SELECT COUNT(*) FROM Fact_Orders").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM Dim_SKU").fetchone()[0] == 0
    quarantine = tmp_path / "ws" / "lake" / "governance" / "quarantine"
    evidence = json.loads((quarantine / "initial_ingest_DQ_BLOCKED_issues.json").read_text(encoding="utf-8"))
    assert evidence["failure_class"] == "DATA_QUALITY" and evidence["report"]["issues"][0]["row_snapshot"]
    history = (tmp_path / "ws" / "lake" / "control" / "stage_history.jsonl").read_text(encoding="utf-8")
    assert '"error_code": "DQ_BLOCKED"' in history
    # the original CSV is byte-identical (no rewrite)
    assert "UNSEEN_SKU_XYZ" in (source / "initial" / "Fact_Order_Items.csv").read_text(encoding="utf-8-sig")


def test_clean_source_passes_gate_and_reports_dq_separately_from_reconciliation(tmp_path):
    result = run_batch(tmp_path / "ws", "initial", source_root=_legacy_source(tmp_path))
    assert result["status"] == "SUCCESS"
    dq_summary = result["metrics"]["ingest"]["result"]["dq"]
    assert dq_summary["blocked"] is False and dq_summary["rules"] > 80 and dq_summary["failed_rows"] == 0
    assert result["functional_passes"] == 18                  # legacy reconciliation checks unchanged


def test_stage3_defense_rejects_an_invalid_reference_in_raw_snapshot(tmp_path):
    source = _legacy_source(tmp_path)
    ws = tmp_path / "ws"
    run_batch(ws, "initial", source_root=source, stop_after="extract")
    raw = ws / "lake" / "raw" / "initial" / "Fact_Order_Items.parquet"
    frame = pd.read_parquet(raw)
    frame.loc[3, "SKU_ID"] = "SNUCK_IN_AFTER_STAGE1"
    frame.to_parquet(raw, index=False)
    with pytest.raises(dq.DQBlocked) as blocked:
        run_batch(ws, "initial", source_root=source, stop_after="transform")
    report = blocked.value.report
    assert report["stage"] == "transform" and report["evaluation_kind"] == "DEFENSE"
    assert report["issues"][0]["invalid_value"] == "SNUCK_IN_AFTER_STAGE1"
    assert not (ws / "lake" / "standardized" / "initial" / "Fact_Sales_Order_Item.parquet").exists()


# ------------------------------------------------------------------ source lock

def _zip_from(folder: Path, mutate=None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for item in sorted(folder.iterdir()):
            data = item.read_bytes()
            if mutate:
                data = mutate(item.name, data)
            if data is not None:
                archive.writestr(item.name, data)
    return buffer.getvalue()


def _legacy_zip_folder(tmp_path):
    contract = json.loads((ROOT / "dashboard/data/classroom_source_contract.json").read_text())
    folder = tmp_path / "pkg"
    folder.mkdir()
    for table in contract["source_tables"]:
        (folder / f"{table}.csv").write_text(",".join(contract["columns"][table]) + "\n", encoding="utf-8")
    (folder / "source_manifest.json").write_text(json.dumps({
        "batch": "initial", "month": "2026-01", "source_tables": contract["source_tables"],
        "columns": contract["columns"]}), encoding="utf-8")
    return folder


def test_lock_rejects_wrong_hash_unknown_version_and_wrong_month(tmp_path):
    data = _zip_from(_legacy_zip_folder(tmp_path))
    assert source_lock.verify_source_zip(data, "initial", version=source_lock.LEGACY_VERSION)["lock_status"] == "UNLOCKED_LEGACY"
    with pytest.raises(source_lock.SourceLockError) as e1:      # locked version: hash cannot match
        source_lock.verify_source_zip(data, "initial", version="classroom_v2_2026_11_16")
    assert e1.value.code == "SOURCE_HASH_MISMATCH"
    with pytest.raises(source_lock.SourceLockError) as e2:
        source_lock.verify_source_zip(data, "initial", version="nope")
    assert e2.value.code == "SOURCE_VERSION_UNKNOWN"
    with pytest.raises(source_lock.SourceLockError) as e3:
        source_lock.verify_source_zip(data, "incremental_03", version=source_lock.LEGACY_VERSION)
    assert e3.value.code == "SOURCE_MONTH_MISMATCH"
    with pytest.raises(source_lock.SourceLockError) as e4:
        source_lock.verify_source_zip(data, "incremental_02_error", version=source_lock.LEGACY_VERSION)
    assert e4.value.code == "SOURCE_BATCH_INVALID"


def test_lock_rejects_missing_table_changed_header_and_manifest_hash_mismatch(tmp_path):
    folder = _legacy_zip_folder(tmp_path)
    missing = _zip_from(folder, lambda n, d: None if n == "Dim_SKU.csv" else d)
    with pytest.raises(source_lock.SourceLockError) as e1:
        source_lock.verify_source_zip(missing, "initial", version=source_lock.LEGACY_VERSION)
    assert e1.value.code == "SOURCE_TABLE_SET_MISMATCH"
    header = _zip_from(folder, lambda n, d: d.replace(b"SKU_ID", b"SKU_IDX", 1) if n == "Dim_SKU.csv" else d)
    with pytest.raises(source_lock.SourceLockError) as e2:
        source_lock.verify_source_zip(header, "initial", version=source_lock.LEGACY_VERSION)
    assert e2.value.code == "SOURCE_COLUMNS_MISMATCH"
    manifest = json.loads((folder / "source_manifest.json").read_text())
    manifest["file_sha256"] = {"Dim_SKU.csv": "0" * 64}
    bad = _zip_from(folder, lambda n, d: json.dumps(manifest).encode() if n == "source_manifest.json" else d)
    with pytest.raises(source_lock.SourceLockError) as e3:
        source_lock.verify_source_zip(bad, "initial", version=source_lock.LEGACY_VERSION)
    assert e3.value.code == "SOURCE_MANIFEST_FILE_HASH_MISMATCH"


def _worker():
    spec = importlib.util.spec_from_file_location("lab_worker_unit", ROOT / "api" / "lab-worker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_worker_stage_source_writes_nothing_when_verification_fails(tmp_path, monkeypatch):
    worker = _worker()
    monkeypatch.setenv("CLASSROOM_SOURCE_VERSION", "classroom_v2_2026_11_16")
    target = tmp_path / "source"
    target.mkdir()
    with pytest.raises(source_lock.SourceLockError):
        worker.stage_source(_zip_from(_legacy_zip_folder(tmp_path)), target, "initial")
    assert list(target.iterdir()) == []                       # rejected BEFORE any write
    monkeypatch.delenv("CLASSROOM_SOURCE_LOCAL_DIR", raising=False)
    monkeypatch.delenv("CLASSROOM_SOURCE_V2_S3_PREFIX", raising=False)
    monkeypatch.delenv("CLASSROOM_SOURCE_V2_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="SOURCE_LOCATION_NOT_CONFIGURED"):
        worker.source_bytes("initial", None)


def test_default_runtime_stays_on_the_legacy_release_until_explicitly_switched(monkeypatch):
    monkeypatch.delenv("CLASSROOM_SOURCE_VERSION", raising=False)
    assert source_lock.active_version() == source_lock.LEGACY_VERSION
    assert "classroom-source-v1" in (ROOT / "api" / "lab-worker.py").read_text(encoding="utf-8")


# ------------------------------------------------------------------ Final package (independent oracle)

@needs_package
def test_final_package_all_ten_zips_match_lock_and_embedded_manifests():
    identities = source_lock.verify_package(PACKAGE / "monthly_source")
    assert len(identities) == 10 and all(i["manifest_verified_files"] for i in identities)
    assert [i["files"]["Fact_Orders.csv"]["rows"] for i in identities[:3]] == [247, 213, 262]
    assert [i["files"]["Fact_Order_Items.csv"]["rows"] for i in identities[:3]] == [359, 303, 382]


@needs_package
def test_final_package_march_has_exactly_one_invalid_sku_detected_by_the_generic_rule(tmp_path):
    ws, src = tmp_path / "ws", tmp_path / "src"
    for batch, month in (("initial", "01"), ("incremental_01", "02"), ("incremental_02", "03")):
        data = (PACKAGE / "monthly_source" / f"classroom-source-2026-{month}.zip").read_bytes()
        identity = source_lock.verify_source_zip(data, batch, version="classroom_v2_2026_11_16")
        src.mkdir(exist_ok=True)
        source_lock.unpack_verified(data, src / batch)
        source_lock.write_identity(src, identity)
        if batch != "incremental_02":
            assert run_batch(ws, batch, source_root=src)["status"] == "SUCCESS"
    before = sqlite3.connect(ws / "er1.sqlite").execute("SELECT COUNT(*) FROM Fact_Order_Items").fetchone()[0]
    with pytest.raises(dq.DQBlocked) as blocked:
        run_batch(ws, "incremental_02", source_root=src)
    issues = blocked.value.report["issues"]
    assert len(issues) == 1 and issues[0]["pk"] == {"Order_Item_ID": "ORD-202603-00001-I1"}
    assert issues[0]["invalid_value"] == "SKU_ERR_UNKNOWN_DEMO"
    assert issues[0]["source_zip_sha256"] == "6e7265c51b6e50599fc154eb8a031a11a0b844c2c18bf03cce8028814a85ba28"
    after = sqlite3.connect(ws / "er1.sqlite").execute("SELECT COUNT(*) FROM Fact_Order_Items").fetchone()[0]
    assert before == after                                    # no March row promoted
    # oracle (test only): applying the QA answer through the correction overlay passes the SAME rules
    patch = json.loads((PACKAGE / "qa_only" / "fix_patch_2026_03_invalid_sku.json").read_text())
    control = ws / "lake" / "control"
    dq.corrections_path(control, "incremental_02").write_text(json.dumps({"correction_set_id": "t", "corrections": [{
        "table": "Fact_Order_Items", "pk": {"Order_Item_ID": patch["key_value"]}, "column": "SKU_ID",
        "original_value": patch["old_value"], "new_value": patch["new_value"], "version": 1}]}), encoding="utf-8")
    result = run_batch(ws, "incremental_02", source_root=src)
    assert result["status"] == "SUCCESS" and result["metrics"]["ingest"]["result"]["dq"]["corrections_applied"] == 1
