"""End-to-end recovery proof on a THROWAWAY local PostgreSQL (never Neon production).

Runs the real Vercel worker code path (`api/lab-worker.py: run_ticket / run_revalidation`) with an
in-memory S3 stand-in, the real Final monthly Source ZIPs, the real Review & Fix API module
(`lib/lab-dq.js` through Node + `pg`) and the real migration SQL:

    Jan publish -> Feb publish -> Mar BLOCKED_DQ (before promote/publish) -> candidates from the
    Neon master -> human correction (versioned) -> revalidate (same rules) -> resume -> Mar publish
    -> Apr..Oct publish, with no duplicate rows and Jan/Feb untouched.

Required environment (the test is skipped, i.e. NOT_TESTED, when anything is missing):
  DQ_TEST_DATABASE_URL   postgres URL of an EMPTY local throwaway database whose name contains "test"
                         (its demo_control/demo_er1 schemas are dropped and recreated!)
  FINAL_SOURCE_PACKAGE   folder TikTok_Shop_Mock_Data_FINAL_1_Error (monthly_source/ + qa_only/ + expected_kpi.csv)
  DQ_TEST_PG_PARENT      (optional) a file next to a node_modules containing `pg`
The QA files are used here only as an independent oracle; the application never reads them.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
DB_URL = os.environ.get("DQ_TEST_DATABASE_URL", "")
PACKAGE = Path(os.environ.get("FINAL_SOURCE_PACKAGE", "")) if os.environ.get("FINAL_SOURCE_PACKAGE") else None
LOCK_VERSION = "classroom_v2_2026_11_16"
ADMIN_KEY = "test-admin-key"
BUCKET = "test-bucket"
BATCHES = ["initial"] + [f"incremental_{i:02d}" for i in range(1, 10)]


def _db_is_throwaway() -> bool:
    if not DB_URL:
        return False
    parsed = urlparse(DB_URL)
    name = (parsed.path or "/").strip("/")
    query = parsed.query
    local = parsed.hostname in (None, "", "localhost", "127.0.0.1") or "host=/" in query
    return bool(re.fullmatch(r"[a-z0-9_]*test[a-z0-9_]*", name)) and local


pytestmark = pytest.mark.skipif(
    not (_db_is_throwaway() and PACKAGE and (PACKAGE / "monthly_source").is_dir()
         and shutil.which("node")),
    reason="needs DQ_TEST_DATABASE_URL (local *test* DB), FINAL_SOURCE_PACKAGE and node")

psycopg = pytest.importorskip("psycopg")


class FakeS3:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.objects[(Bucket, Key)] = bytes(Body)

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    saved_environ = dict(os.environ)      # the worker mutates os.environ directly; restore it afterwards
    mp = pytest.MonkeyPatch()
    for key, value in {
        "CLASSROOM_SOURCE_VERSION": LOCK_VERSION,
        "CLASSROOM_SOURCE_LOCAL_DIR": str(PACKAGE / "monthly_source"),
        "CLASSROOM_STORAGE_BUCKET": BUCKET,
        "CLASSROOM_LAB_WRITER_URL": DB_URL,
        "CLASSROOM_LAB_ADMIN_KEY": ADMIN_KEY,
    }.items():
        mp.setenv(key, value)
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("lab_worker_under_test", ROOT / "api" / "lab-worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    s3 = FakeS3()
    worker.storage = lambda: s3
    # throwaway schema = real bootstrap + real DQ migration
    with psycopg.connect(DB_URL, autocommit=True) as db:
        db.execute("DROP SCHEMA IF EXISTS demo_control CASCADE; DROP SCHEMA IF EXISTS demo_er1 CASCADE")
        db.execute((ROOT / "sql" / "neon_er1_demo_bootstrap.sql").read_text(encoding="utf-8"))
        db.execute((ROOT / "sql" / "neon_dq_recovery_migration.sql").read_text(encoding="utf-8"))
    yield {"worker": worker, "s3": s3, "ctx": {}}
    mp.undo()
    os.environ.clear()
    os.environ.update(saved_environ)
    for name in [m for m in sys.modules if m.startswith("pipeline.ci_lab")]:
        sys.modules.pop(name, None)       # drop modules bound to the temporary workspace


def q(sql, params=()):
    with psycopg.connect(DB_URL) as db:
        return db.execute(sql, params).fetchall()


def sign(claim: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(claim).encode()).rstrip(b"=").decode()
    return encoded + "." + hmac.new(ADMIN_KEY.encode(), encoded.encode(), hashlib.sha256).hexdigest()


def run_month(env, batch: str):
    state = q("SELECT cycle_number,last_run_id::text FROM demo_control.dataset_state WHERE dataset_key='classroom'")[0]
    claim = {"batch": batch, "previous_run_id": "0" if batch == "initial" else state[1], "cycle": state[0],
             "stage": None, "run_all": True, "source_upload_id": None, "nonce": str(uuid.uuid4()),
             "expires_at": int(time.time() * 1000) + 600000}
    return env["worker"].run_ticket(sign(claim))


def api(method, op, query=None, body=None):
    payload = json.dumps({"method": method, "query": {"dq": op, **(query or {})}, "body": body})
    child_env = {**os.environ, "DQ_TEST_DATABASE_URL": DB_URL, "CLASSROOM_LAB_ADMIN_KEY": ADMIN_KEY}
    done = subprocess.run(["node", str(ROOT / "tests" / "integration" / "dq_api_harness.mjs")],
                          input=payload, capture_output=True, text=True, env=child_env, cwd=str(ROOT), timeout=60)
    assert done.returncode == 0, done.stderr[-800:]
    out = json.loads(done.stdout)
    return out["status"], out["json"]


def oracle_kpi():
    with (PACKAGE / "expected_kpi.csv").open(encoding="utf-8-sig", newline="") as handle:
        return {row["month"]: row for row in csv.DictReader(handle)}


# ---------------------------------------------------------------- the story

def test_01_all_ten_zips_verify_against_lock():
    from pipeline import source_lock
    identities = source_lock.verify_package(PACKAGE / "monthly_source", LOCK_VERSION)
    assert [i["lock_status"] for i in identities] == ["LOCKED_SHA256_VERIFIED"] * 10
    assert identities[2]["zip_sha256"] == "6e7265c51b6e50599fc154eb8a031a11a0b844c2c18bf03cce8028814a85ba28"


def test_02_hash_mismatch_is_rejected_before_any_write(env):
    from pipeline import source_lock
    data = bytearray((PACKAGE / "monthly_source" / "classroom-source-2026-02.zip").read_bytes())
    data[-30] ^= 0xFF                                    # corrupt one byte
    with pytest.raises(source_lock.SourceLockError) as error:
        source_lock.verify_source_zip(bytes(data), "incremental_01", version=LOCK_VERSION)
    assert error.value.code in ("SOURCE_HASH_MISMATCH",)
    assert q("SELECT COUNT(*) FROM demo_control.pipeline_runs")[0][0] == 0   # nothing was created


def test_03_january_and_february_publish(env):
    for batch in ("initial", "incremental_01"):
        result = run_month(env, batch)
        assert result["summary"]["status"] == "SUCCESS" and result["summary"]["no_duplicate_sales_items"]
    rows = q("SELECT batch,source_zip_sha256,source_version,is_current FROM demo_control.published_snapshot ORDER BY published_at")
    assert [r[0] for r in rows] == ["initial", "incremental_01"]
    assert rows[0][1] == "b3a5de6e4dc4bf84f4de0671d9e115b493cc4ce7571049ff3a446335b5002b8f"
    assert rows[1][2] == LOCK_VERSION and [r[3] for r in rows] == [False, True]
    art = q("SELECT content_sha256 FROM demo_control.pipeline_artifacts WHERE artifact_type='SOURCE' ORDER BY created_at")
    assert [a[0] for a in art][1] == "6ec2339e91393f23d7ba1fe3712d742f50c23b0217262fa45b6a65c6063ce2a9"
    gate = q("SELECT COUNT(*),COUNT(*) FILTER (WHERE status='FAIL') FROM demo_control.dq_rule_result "
             "WHERE evaluation_kind='GATE'")[0]
    assert gate[0] > 0 and gate[1] == 0                  # real PASS evaluations persisted, none failed
    env["ctx"]["feb_orders"] = q('SELECT COUNT(*) FROM demo_er1."Fact_Orders"')[0][0]
    env["ctx"]["feb_items"] = q('SELECT COUNT(*) FROM demo_er1."Fact_Order_Items"')[0][0]
    env["ctx"]["snapshot_hashes"] = {k: hashlib.sha256(v).hexdigest() for (_, k), v in env["s3"].objects.items()
                                     if k.endswith("warehouse.zip")}


def test_04_march_is_blocked_before_promote_and_publish(env):
    worker = env["worker"]
    with pytest.raises(worker.BlockedDQ) as blocked:
        run_month(env, "incremental_02")
    run_id = blocked.value.run_id
    assert blocked.value.issue_count == 1 and blocked.value.stage == "ingest"
    status, summary = q("SELECT status,result_summary FROM demo_control.pipeline_runs WHERE run_id=%s", (run_id,))[0]
    assert status == "BLOCKED_DQ" and summary["failure_class"] == "DATA_QUALITY"
    assert summary["source_identity"]["zip_sha256"] == "6e7265c51b6e50599fc154eb8a031a11a0b844c2c18bf03cce8028814a85ba28"
    # no Stage 2-5 success, nothing promoted into ER1, no snapshot for March
    stages = dict(q("SELECT stage_name,status FROM demo_control.stage_runs WHERE run_id=%s", (run_id,)))
    assert stages == {"ingest": "FAILED"}
    assert q('SELECT COUNT(*) FROM demo_er1."Fact_Orders"')[0][0] == env["ctx"]["feb_orders"]
    assert q('SELECT COUNT(*) FROM demo_er1."Fact_Order_Items"')[0][0] == env["ctx"]["feb_items"]
    assert q("SELECT COUNT(*) FROM demo_control.published_snapshot WHERE batch='incremental_02'")[0][0] == 0
    assert q("SELECT phase FROM demo_control.dataset_state")[0][0] == "RUN2_READY"
    # durable, run-scoped evidence outside /tmp
    assert (BUCKET, f"vercel-lab/blocked/{run_id}/dq_report.json") in env["s3"].objects
    # persisted issue = original row evidence
    issue = q("SELECT rule_id,table_name,source_row_no,pk_json,column_name,invalid_value,source_file_sha256,"
              "source_zip_sha256,status,row_snapshot,issue_id::text FROM demo_control.dq_issue")[0]
    assert issue[0] == "REFERENCE_EXISTS:Fact_Order_Items.SKU_ID->Dim_SKU.SKU_ID"
    assert issue[1:6] == ("Fact_Order_Items", 1, {"Order_Item_ID": "ORD-202603-00001-I1"}, "SKU_ID", "SKU_ERR_UNKNOWN_DEMO")
    assert issue[6] == "cee3ecb4a6942d33d46835ec1735bde4e880044bddf27e43b66aa6f8c1e80892" and issue[8] == "OPEN"
    assert issue[9]["Order_ID"] == "ORD-202603-00001"
    rule = q("SELECT checked_rows,failed_rows,status FROM demo_control.dq_rule_result WHERE run_id=%s AND "
             "rule_id='REFERENCE_EXISTS:Fact_Order_Items.SKU_ID->Dim_SKU.SKU_ID'", (run_id,))[0]
    assert rule[1] == 1 and rule[0] > 300 and rule[2] == "FAIL"
    env["ctx"].update(blocked_run=run_id, issue_id=issue[10])


def test_05_api_state_and_candidates_come_from_neon_master(env):
    status, state = api("GET", "state")
    assert status == 200 and state["blocked"] and state["run"]["batch"] == "incremental_02"
    assert len(state["issues"]) == 1 and state["issues"][0]["invalid_value"] == "SKU_ERR_UNKNOWN_DEMO"
    status, cand = api("GET", "candidates", {"issue_id": env["ctx"]["issue_id"]})
    assert status == 200 and cand["master_table"] == "Dim_SKU" and cand["count"] == 140
    ids = {row["SKU_ID"] for row in cand["candidates"]}
    expected = json.loads((PACKAGE / "qa_only" / "fix_patch_2026_03_invalid_sku.json").read_text())["new_value"]
    assert expected in ids                               # oracle: the true SKU is selectable, never preselected
    assert cand["hint"]["kind"] == "PRODUCT_GROUP_BY_BASE_PRICE" and "SKU_ERR_UNKNOWN_DEMO" not in ids
    env["ctx"]["true_sku"] = expected


def test_06_correction_validation_audit_and_idempotency(env):
    issue = env["ctx"]["issue_id"]
    good = {"issue_id": issue, "corrected_value": env["ctx"]["true_sku"], "actor": "data.owner",
            "reason": "Confirmed from the original marketplace order slip", "evidence_ref": "SLIP-ORD-202603-00001",
            "expected_version": 0, "idempotency_key": "key-0001-abcdef"}
    assert api("POST", "correct", body={**good, "reason": "short"})[0] == 400
    status, data = api("POST", "correct", body={**good, "corrected_value": "NOT_A_SKU"})
    assert status == 422 and data["error_code"] == "VALUE_NOT_IN_MASTER"
    assert q("SELECT COUNT(*) FROM demo_control.dq_correction")[0][0] == 0
    # before any valid correction, revalidation is refused (issue still OPEN) and resume is refused by the worker
    assert api("POST", "revalidate", body={"actor": "data.owner"})[1]["error_code"] == "ISSUES_UNCORRECTED"
    runs_before = q("SELECT COUNT(*) FROM demo_control.pipeline_runs")[0][0]
    with pytest.raises(Exception) as refused:
        run_month(env, "incremental_02")
    assert "DQ_REVALIDATION_REQUIRED" in str(refused.value)
    # refused before begin_run: no new run row, no duplicate issue, no touch of the previous month's failure marker
    assert q("SELECT COUNT(*) FROM demo_control.pipeline_runs")[0][0] == runs_before
    assert q("SELECT COUNT(*) FROM demo_control.dq_issue")[0][0] == 1
    # valid correction
    status, data = api("POST", "correct", body=good)
    assert status == 201 and data["version"] == 1
    status, replay = api("POST", "correct", body=good)           # double submit
    assert status == 200 and replay["replayed"] is True
    status, conflict = api("POST", "correct", body={**good, "idempotency_key": "key-0002-abcdef"})
    assert status == 409 and conflict["error_code"] == "VERSION_CONFLICT"
    row = q("SELECT version,original_value,corrected_value,actor,reason,evidence_ref FROM demo_control.dq_correction")
    assert row == [(1, "SKU_ERR_UNKNOWN_DEMO", env["ctx"]["true_sku"], "data.owner",
                    "Confirmed from the original marketplace order slip", "SLIP-ORD-202603-00001")]
    with psycopg.connect(DB_URL) as db:                           # append-only ledger
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute("UPDATE demo_control.dq_correction SET corrected_value='X'")
    with psycopg.connect(DB_URL) as db:                           # original evidence immutable
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute("UPDATE demo_control.dq_issue SET invalid_value='X'")
    assert q("SELECT status FROM demo_control.dq_issue")[0][0] == "CORRECTED"
    # the source ZIP is untouched
    zip_hash = hashlib.sha256((PACKAGE / "monthly_source" / "classroom-source-2026-03.zip").read_bytes()).hexdigest()
    assert zip_hash == "6e7265c51b6e50599fc154eb8a031a11a0b844c2c18bf03cce8028814a85ba28"


def test_07_resume_is_refused_until_revalidation_passes(env):
    with pytest.raises(RuntimeError) as refused:
        run_month(env, "incremental_02")
    assert "DQ_REVALIDATION_REQUIRED" in str(refused.value)
    assert q("SELECT COUNT(*) FROM demo_control.published_snapshot WHERE batch='incremental_02'")[0][0] == 0


def test_08_invalid_correction_fails_revalidation_with_same_rule(env):
    issue = env["ctx"]["issue_id"]
    # Simulate a bad ledger entry that bypassed the API (e.g. a stale master): the engine must still catch it.
    q_ctx = q("SELECT correction_id::text FROM demo_control.dq_correction")[0][0]
    with psycopg.connect(DB_URL) as db:
        db.execute("INSERT INTO demo_control.dq_correction(issue_id,version,original_value,corrected_value,actor,reason,"
                   "evidence_ref,supersedes_correction_id,idempotency_key) VALUES (%s,2,'SKU_ERR_UNKNOWN_DEMO',"
                   "'STILL_NOT_A_SKU','tester','forced bad correction for test','TEST',%s,'key-bad-000000')",
                   (issue, q_ctx))
    _, ticket = api("POST", "revalidate", body={"actor": "tester"})
    result = env["worker"].run_revalidation(ticket["ticket"])
    assert result["status"] == "FAIL" and result["summary"]["failed_rows"] == 1
    assert q("SELECT status FROM demo_control.dq_issue")[0][0] == "OPEN"
    assert q("SELECT status FROM demo_control.pipeline_runs WHERE run_id=%s", (env["ctx"]["blocked_run"],))[0][0] == "BLOCKED_DQ"
    # human supplies a correct version 3 (expected_version = 2)
    status, data = api("POST", "correct", body={
        "issue_id": issue, "corrected_value": env["ctx"]["true_sku"], "actor": "data.owner",
        "reason": "Re-confirmed against the original order slip", "evidence_ref": "SLIP-ORD-202603-00001",
        "expected_version": 2, "idempotency_key": "key-0003-abcdef"})
    assert status == 201 and data["version"] == 3


def test_09_revalidate_passes_then_resume_publishes_march(env):
    _, ticket = api("POST", "revalidate", body={"actor": "data.owner"})
    result = env["worker"].run_revalidation(ticket["ticket"])
    assert result["status"] == "PASS" and result["summary"]["failed_rows"] == 0
    assert q("SELECT status FROM demo_control.pipeline_runs WHERE run_id=%s", (env["ctx"]["blocked_run"],))[0][0] == "READY_TO_RESUME"
    assert q("SELECT status FROM demo_control.dq_issue")[0][0] == "REVALIDATED"
    state = api("GET", "state")[1]
    assert state["revalidated"] is True and state["ready_to_resume"] is True
    resumed = run_month(env, "incremental_02")
    assert resumed["summary"]["status"] == "SUCCESS" and resumed["summary"]["no_duplicate_sales_items"]
    snap = q("SELECT batch,source_zip_sha256,correction_set_id,is_current FROM demo_control.published_snapshot "
             "WHERE batch='incremental_02'")[0]
    assert snap[1] == "6e7265c51b6e50599fc154eb8a031a11a0b844c2c18bf03cce8028814a85ba28"
    assert snap[2] and snap[3] is True
    assert q("SELECT status FROM demo_control.dq_issue")[0][0] == "RESOLVED"
    old = q("SELECT status,result_summary->>'superseded_by' FROM demo_control.pipeline_runs WHERE run_id=%s",
            (env["ctx"]["blocked_run"],))[0]
    assert old == ("CANCELLED", resumed["run_id"])
    sku = q('SELECT "SKU_ID" FROM demo_er1."Fact_Order_Items" WHERE "Order_Item_ID"=%s', ("ORD-202603-00001-I1",))[0][0]
    assert sku == env["ctx"]["true_sku"]
    # Jan/Feb warehouse snapshots are byte-identical to what was published before March
    for key, digest in env["ctx"]["snapshot_hashes"].items():
        assert hashlib.sha256(env["s3"].objects[(BUCKET, key)]).hexdigest() == digest
    # a double click / retry of the same month cannot create duplicates
    with pytest.raises(Exception):
        run_month(env, "incremental_02")
    assert q('SELECT COUNT(*),COUNT(DISTINCT "Order_Item_ID") FROM demo_er1."Fact_Order_Items"')[0][0] == \
        q('SELECT COUNT(DISTINCT "Order_Item_ID") FROM demo_er1."Fact_Order_Items"')[0][0]


def test_10_continue_april_to_october_and_match_independent_oracle(env):
    last = None
    for batch in BATCHES[3:]:
        last = run_month(env, batch)
        assert last["summary"]["status"] == "SUCCESS"
    assert q("SELECT COUNT(*) FROM demo_control.published_snapshot")[0][0] == 10
    assert q("SELECT COUNT(*) FROM demo_control.published_snapshot WHERE is_current")[0][0] == 1
    months = {row["month"]: row for row in last["summary"]["business"]["months"]}
    expected = oracle_kpi()
    assert set(expected) == set(months)
    for month, want in expected.items():
        got = months[month]
        assert abs(float(got["net"]) - float(want["net_revenue"])) < 0.05, month
        assert abs(float(got["gross"]) - float(want["gross_reference_sales"])) < 0.05, month
        # Contribution profit accumulates per-line cent rounding in the existing (unchanged) formulas;
        # the oracle rounds differently. Net/Gross match to the satang; profit may differ by a few satang.
        deviation = abs(float(got["profit"]) - float(want["contribution_profit"]))
        print(f"PROFIT_DEVIATION {month} {deviation:.2f}")
        assert deviation <= 0.50, month
    # Business KPI FAIL does not block data: February misses its revenue target yet was published.
    assert expected["2026-02"]["revenue_status"] == "FAIL"
    assert q("SELECT COUNT(*) FROM demo_control.published_snapshot WHERE batch='incremental_01'")[0][0] == 1
