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
from datetime import datetime, timedelta
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
        "CLASSROOM_EVIDENCE_ORIGIN": "LOCAL_REAL_SOURCE_TEST",       # real Final source through the real worker, but a throwaway test database (not Production)
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
        db.execute("DROP SCHEMA IF EXISTS demo_ml CASCADE")
        db.execute((ROOT / "sql" / "neon_demo_ml_migration.sql").read_text(encoding="utf-8"))
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


SUMMARY_DIR = Path(os.environ.get("DQ_TEST_SUMMARY_DIR", "")) if os.environ.get("DQ_TEST_SUMMARY_DIR") else None


def api(method, op, query=None, body=None, module="dq"):
    key = "fc" if module == "forecast" else "dq"
    payload = json.dumps({"method": method, "module": module, "query": {key: op, **(query or {})}, "body": body})
    child_env = {**os.environ, "DQ_TEST_DATABASE_URL": DB_URL, "CLASSROOM_LAB_ADMIN_KEY": ADMIN_KEY,
                 "DQ_TEST_SUMMARY_DIR": str(SUMMARY_DIR or "")}
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


# ------------------------------------------------------------------ journey after March

def fc(method, op, query=None, body=None):
    return api(method, op, query, body, module="forecast")


def oracle_groups():
    with (PACKAGE / "expected_group_monthly.csv").open(encoding="utf-8-sig", newline="") as handle:
        out = {}
        for row in csv.DictReader(handle):
            out.setdefault(row["month"], {})[row["product_group_id"]] = float(row["net_revenue"])
        return out


def publish_summaries(env):
    """Copy batch.json of every run out of the in-memory object storage for the Node evaluation harness."""
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    for (bucket, key), data in env["s3"].objects.items():
        match = re.fullmatch(r"vercel-lab/results/([0-9a-f-]{36})/batch\.json", key)
        if match:
            (SUMMARY_DIR / f"{match.group(1)}.json").write_bytes(data)


def forecast_for(env, month, actor="business.owner"):
    status, data = fc("POST", "generate", body={"month": month, "actor": actor})
    assert status == 202, data
    result = env["worker"].run_forecast(data["ticket"])
    assert result["status"] == "DRAFT"
    return result["summary"]


def test_10_run_to_may_then_stop_and_june_is_locked_until_sealed(env):
    for batch in ("incremental_03", "incremental_04"):
        assert run_month(env, batch)["summary"]["status"] == "SUCCESS"
    # server-side gate: the worker refuses June (no official forecast), nothing is created
    runs_before = q("SELECT COUNT(*) FROM demo_control.pipeline_runs")[0][0]
    with pytest.raises(RuntimeError) as locked:
        run_month(env, "incremental_05")
    assert "LAB_FORECAST_NOT_SEALED" in str(locked.value)
    assert q("SELECT COUNT(*) FROM demo_control.pipeline_runs")[0][0] == runs_before
    status, st = fc("GET", "status")
    assert st["published_through"] == "2026-05"
    june = next(m for m in st["months"] if m["month"] == "2026-06")
    assert june["can_generate"] is True and june["target"]["revenue_target_thb"] == 94000
    july = next(m for m in st["months"] if m["month"] == "2026-07")
    assert july["can_generate"] is False and july["reason"].startswith("PUBLISHED_THROUGH")
    # cannot forecast July yet (cutoff not published)
    assert fc("POST", "generate", body={"month": "2026-07", "actor": "x"})[0] == 409


def test_11_may_actual_gates_match_the_independent_oracle(env):
    publish_summaries(env)
    last = [r for r in q("SELECT run_id::text FROM demo_control.dataset_state, demo_control.pipeline_runs "
                         "WHERE run_id=last_run_id")][0][0]
    summary = json.loads((SUMMARY_DIR / f"{last}.json").read_text())
    shop = {m["month"]: m for m in summary["business"]["shop_months"]}
    may, expected = shop["2026-05"], oracle_kpi()["2026-05"]
    assert abs(may["net"] - float(expected["net_revenue"])) < 0.05 and abs(may["net"] - 83821.69) < 0.05
    assert abs(may["gross"] - float(expected["gross_reference_sales"])) < 0.05
    assert abs(may["profit"] - float(expected["contribution_profit"])) <= 0.50 and abs(may["profit"] - 1875.33) <= 0.50
    gates = may["gates"]
    assert gates["revenue"]["status"] == "FAIL" and gates["revenue"]["target"] == 91000.0
    assert gates["profit_protection"]["status"] == "FAIL" and abs(gates["profit_protection"]["rate_pct"] - 2.05) < 0.02
    # Marketing GAP: the five components from the independent oracle, over Gross Reference Sales
    numerator = sum(float(expected[k]) for k in ("campaign_price_reduction", "voucher_discount", "affiliate_cost", "ads_cost", "sample_cost"))
    assert abs(gates["marketing_gap"]["numerator"] - numerator) < 0.10
    assert abs(gates["marketing_gap"]["rate_pct"] - 100 * numerator / float(expected["gross_reference_sales"])) < 0.02
    assert gates["marketing_gap"]["status"] in ("PASS", "FAIL")
    # business FAIL did not block the publication
    assert q("SELECT COUNT(*) FROM demo_control.published_snapshot WHERE batch='incremental_04'")[0][0] == 1
    assert gates["target_policy"]["label"] == "SIMULATED_PRECONFIGURED_FOR_CLASSROOM"


def test_12_june_forecast_uses_data_through_may_only_and_is_honest_about_method(env):
    draft = forecast_for(env, "2026-06")
    assert draft["published_through"] == "2026-05" and draft["training_cutoff_date"] == "2026-05-31"
    assert draft["method_type"] == "BASELINE" and draft["validation"]["status"] == "INSUFFICIENT_VALIDATION"
    assert sorted(draft["predictions"]) == ["PG01", "PG02", "PG03", "PG04", "PG05"]
    assert abs(sum(draft["predictions"].values()) - draft["shop_prediction"]) < 0.01
    # independent oracle: the naive baseline equals May's group Net Revenue from the QA file
    may = oracle_groups()["2026-05"]
    naive = draft["validation"]["baselines_all_origins"]["naive_previous_month"]
    assert draft["model_name"] in ("naive_previous_month", "trailing_3_month_mean")
    if draft["model_name"] == "naive_previous_month":
        for group, value in draft["predictions"].items():
            assert abs(value - may[group]) < 0.05
    assert naive["origins"] == 4
    row = q("SELECT status,is_official,method_type FROM demo_ml.forecast_run WHERE forecast_run_id=%s", (draft["forecast_run_id"],))[0]
    assert row == ("DRAFT", False, "BASELINE")
    assert (BUCKET, f"vercel-lab/forecast/{draft['forecast_run_id']}/manifest.json") in env["s3"].objects
    # MLOps evidence is recorded next to (never instead of) the official forecast: 5 months => 2 walk-forward origins => experimental only
    ml = draft["mlops"]
    assert ml["status"] == "RECORDED" and ml["evaluation_status"] == "EXPERIMENTAL_INSUFFICIENT_VALIDATION"
    stored = {key for (_bucket, key) in env["s3"].objects}
    for name in ("baseline_trailing_3_month_mean", "ridge_base", "ridge_marketing"):
        assert f"{ml['run_path']}/models/{name}.json" in stored
    assert f"{ml['feature_set_path']}/features.parquet" in stored
    env["ctx"]["june_draft"] = draft


def test_12b_ml_can_never_become_the_official_forecast_automatically(env, monkeypatch):
    from pipeline import monthly_forecast as mf_module
    real = mf_module.generate_forecast
    calls = []

    def spy(rows, target, **kw):
        calls.append(kw.get("allow_ml", True))
        return real(rows, target, **kw)
    monkeypatch.setattr(mf_module, "generate_forecast", spy)
    before = q("SELECT COUNT(*) FROM demo_ml.forecast_run")[0][0]
    forecast_for(env, "2026-06")
    assert calls[0] is False                                           # the worker's official selection call forbids ML
    assert q("SELECT COUNT(*) FROM demo_ml.forecast_run")[0][0] == before + 1

    def ml_result(rows, target, **kw):                                  # a regression that returns ML must be stopped before anything is saved
        result = real(rows, target, **kw)
        return {**result, "method_type": "ML", "model_name": "ridge_pooled_group_month"}
    monkeypatch.setattr(mf_module, "generate_forecast", ml_result)
    status, data = fc("POST", "generate", body={"month": "2026-06", "actor": "business.owner"})
    assert status == 202
    with pytest.raises(RuntimeError) as blocked:
        env["worker"].run_forecast(data["ticket"])
    assert "LAB_POLICY_ML_NOT_OFFICIAL" in str(blocked.value)
    assert q("SELECT COUNT(*) FROM demo_ml.forecast_run")[0][0] == before + 1      # nothing was written by the blocked attempt
    monkeypatch.setattr(mf_module, "generate_forecast", real)
    # drafts per month are capped (a replayed or repeated request cannot create unlimited drafts)
    cap = 5
    while q("SELECT COUNT(*) FROM demo_ml.forecast_run WHERE target_month='2026-06-01' AND status='DRAFT'")[0][0] < cap - 1:
        forecast_for(env, "2026-06")
    status, held = fc("POST", "generate", body={"month": "2026-06", "actor": "business.owner"})
    assert status == 202                                               # 4 drafts: one more is still allowed
    forecast_for(env, "2026-06")                                       # 5th draft
    status, refused = fc("POST", "generate", body={"month": "2026-06", "actor": "business.owner"})
    assert status == 429 and refused["error_code"] == "DRAFT_LIMIT"
    with pytest.raises(RuntimeError) as replay:                         # the ticket issued earlier cannot be replayed past the cap either
        env["worker"].run_forecast(held["ticket"])
    assert "LAB_DRAFT_LIMIT" in str(replay.value)
    assert q("SELECT COUNT(*) FROM demo_ml.forecast_run WHERE target_month='2026-06-01' AND status='DRAFT'")[0][0] == cap


def test_13_seal_once_is_immutable_and_unlocks_june(env):
    draft = env["ctx"]["june_draft"]
    status, bad = fc("POST", "seal", body={"forecast_run_id": draft["forecast_run_id"]})
    assert status == 400                                   # actor required
    other_id = [r[0] for r in q("SELECT forecast_run_id::text FROM demo_ml.forecast_run WHERE target_month='2026-06-01' AND status='DRAFT' AND forecast_run_id::text<>%s", (draft["forecast_run_id"],))][0]
    other = {"forecast_run_id": other_id}                  # other drafts exist (retries); only one can ever become official
    status, sealed = fc("POST", "seal", body={"forecast_run_id": draft["forecast_run_id"], "actor": "business.owner"})
    assert status == 200 and sealed["status"] == "SEALED"
    assert fc("POST", "seal", body={"forecast_run_id": draft["forecast_run_id"], "actor": "x"})[0] == 409
    assert fc("POST", "seal", body={"forecast_run_id": other["forecast_run_id"], "actor": "x"})[0] == 409
    assert fc("POST", "generate", body={"month": "2026-06", "actor": "x"})[0] == 409
    with psycopg.connect(DB_URL) as db:                    # DB-level immutability
        with pytest.raises(Exception):
            db.execute("UPDATE demo_ml.forecast_result SET predicted_net_revenue=1 WHERE forecast_run_id=%s", (draft["forecast_run_id"],))
    f = fc("GET", "forecast", {"month": "2026-06"})[1]
    assert f["official"]["forecast_run_id"] == draft["forecast_run_id"] and f["plan_status"] == "NO_SELECTED_PLAN"
    assert f["official"]["results"] == draft["predictions"]          # persisted exactly as generated (survives refresh)
    env["ctx"]["june_sealed"] = {"results": f["official"]["results"], "sealed_at": str(f["official"]["sealed_at"]), "forecast_run_id": f["official"]["forecast_run_id"],
                                 "shop": f["official"]["shop_forecast"]}


def test_14_scenario_is_pre_target_only_recomputed_server_side_and_append_only(env):
    base = {"month": "2026-06", "plan_code": "A", "plan_title": "Ads +10%", "actor": "business.owner",
            "reason": "Try more ads under stated demand assumptions",
            "assumptions": {"cogs_rate_of_base": 0.4, "platform_fee_rate_of_net": 0.1, "fulfillment_cost_per_order": 12,
                            "affiliate_rate": 0.08, "affiliate_eligible_share_of_net": 0.5, "free_sample_cost": 1000, "claim_cost": 400},
            "controls": {"ads_budget": {g: 3200 for g in ("PG01", "PG02", "PG03", "PG04", "PG05")}},
            "baskets": [{"orders": 300, "lines": [{"group": "PG01", "units": 1, "base_price": 199},
                                                    {"group": "PG02", "units": 1, "base_price": 229}]},
                        {"orders": 250, "lines": [{"group": "PG03", "units": 1, "base_price": 279}]}]}
    status, sim = fc("POST", "simulate", body=base)
    assert status == 200 and sim["persisted"] is False and sim["result"]["kind"] == "WHAT_IF_ASSUMPTIONS_NOT_A_PREDICTION"
    assert q("SELECT COUNT(*) FROM demo_ml.scenario_decision")[0][0] == 0         # trying a plan stores nothing
    status, v1 = fc("POST", "seal_plan", body=base)
    assert status == 201 and v1["decision_version"] == 1
    base2 = {**base, "plan_code": "B", "plan_title": "Ads +20%", "controls": {"ads_budget": {g: 3500 for g in ("PG01", "PG02", "PG03", "PG04", "PG05")}}}
    status, v2 = fc("POST", "seal_plan", body=base2)
    assert status == 201 and v2["decision_version"] == 2
    rows = q("SELECT decision_version,supersedes_decision_id IS NOT NULL,approved_target_amount::float,calculator_version FROM demo_ml.scenario_decision ORDER BY 1")
    assert rows == [(1, False, 94000.0, "scenario-calc-2"), (2, True, 94000.0, "scenario-calc-2")]
    with psycopg.connect(DB_URL) as db:
        with pytest.raises(Exception):
            db.execute("UPDATE demo_ml.scenario_decision SET plan_title='x'")
    # the forecast itself did not change
    assert fc("GET", "forecast", {"month": "2026-06"})[1]["official"]["results"] == env["ctx"]["june_draft"]["predictions"]


def test_15_june_publishes_then_evaluation_uses_the_same_sealed_forecast(env):
    run_month(env, "incremental_05")
    # official forecast can no longer be created/revised after the target month started
    assert fc("POST", "generate", body={"month": "2026-06", "actor": "x"})[0] == 409
    plan = {"month": "2026-06", "plan_code": "C", "plan_title": "late", "actor": "x", "reason": "too late to revise", "controls": {}, "assumptions": {}, "baskets": []}
    assert fc("POST", "seal_plan", body=plan)[0] == 409
    publish_summaries(env)
    status, ev = fc("GET", "evaluation", {"month": "2026-06"})
    assert status == 200 and ev["status"] == "OK"
    sealed = env["ctx"]["june_draft"]
    assert ev["forecast"]["id"] == sealed["forecast_run_id"]
    actual = oracle_groups()["2026-06"]
    for group in ev["evaluation"]["groups"]:
        assert abs(group["actual"] - actual[group["group"]]) < 0.05
        assert group["error"] == pytest.approx(group["actual"] - sealed["predictions"][group["group"]], abs=0.02)   # Actual - Forecast
        if actual[group["group"]] > 0:
            assert group["ape_pct"] == pytest.approx(100 * abs(group["error"]) / group["actual"], abs=0.02)
    shop_actual = sum(actual.values())
    assert ev["evaluation"]["shop"]["actual"] == pytest.approx(shop_actual, abs=0.1)
    assert ev["plan"]["status"] == "SELECTED" and ev["plan"]["version"] == 2 and ev["plan"]["evidence_of_execution"] == "NOT_VERIFIED"


def test_16_rolling_july_to_october_every_month_forecast_sealed_before_actual(env, monkeypatch):
    from pipeline.mlops import monitoring as monitoring_module
    real_record = monitoring_module.record_month

    def boom(*_a, **_k):
        raise RuntimeError("injected monitoring failure")
    for month, batch in (("2026-07", "incremental_06"), ("2026-08", "incremental_07"), ("2026-09", "incremental_08"), ("2026-10", "incremental_09")):
        with pytest.raises(RuntimeError) as locked:                   # the gate cannot be bypassed
            run_month(env, batch)
        assert "LAB_FORECAST_NOT_SEALED" in str(locked.value)
        draft = forecast_for(env, month)
        previous = f"2026-{int(month[5:]) - 1:02d}"
        assert draft["published_through"] == previous                  # only data through the previous month
        assert fc("POST", "seal", body={"forecast_run_id": draft["forecast_run_id"], "actor": "business.owner"})[0] == 200
        sealed_at = q("SELECT sealed_at FROM demo_ml.forecast_run WHERE forecast_run_id=%s", (draft["forecast_run_id"],))[0][0]
        if month == "2026-09":                                           # a monitoring failure must never fail or change a publish
            monkeypatch.setattr(monitoring_module, "record_month", boom)
        published = run_month(env, batch)
        monkeypatch.setattr(monitoring_module, "record_month", real_record)
        assert published["summary"]["status"] == "SUCCESS"
        env["ctx"].setdefault("monitoring_status", {})[month] = published["summary"].get("monitoring", {})
        first_ingest = q("SELECT MIN(started_at) FROM demo_control.pipeline_runs WHERE result_summary->>'batch'=%s", (batch,))[0][0]
        assert sealed_at < first_ingest                                # event order: seal BEFORE ingest
        env["ctx"].setdefault("methods", {})[month] = (draft["method_type"], draft["validation"]["status"])
    publish_summaries(env)
    status, all_eval = fc("GET", "evaluations")
    assert status == 200 and len(all_eval["months"]) == 5              # June..October out-of-sample comparisons
    oracle = oracle_groups()
    abs_sum = act_sum = 0.0
    for item in all_eval["months"]:
        sealed = fc("GET", "forecast", {"month": item["month"]})[1]["official"]["results"]
        for group, value in sealed.items():
            abs_sum += abs(oracle[item["month"]][group] - value)
            act_sum += oracle[item["month"]][group]
    assert all_eval["aggregate"]["group_wape_pct"] == pytest.approx(100 * abs_sum / act_sum, abs=0.05)
    assert q("SELECT COUNT(*) FROM demo_control.published_snapshot")[0][0] == 10
    assert q("SELECT COUNT(*) FROM demo_ml.forecast_run WHERE is_official")[0][0] == 5
    # July onward has >= 3 walk-forward origins, so the challenger was genuinely evaluated
    assert env["ctx"]["methods"]["2026-07"][1] == "OK"
    # every month still matches the independent KPI oracle
    last = q("SELECT last_run_id::text FROM demo_control.dataset_state")[0][0]
    months = {m["month"]: m for m in json.loads((SUMMARY_DIR / f"{last}.json").read_text())["business"]["months"]}
    for month, want in oracle_kpi().items():
        assert abs(float(months[month]["net"]) - float(want["net_revenue"])) < 0.05
        assert abs(float(months[month]["profit"]) - float(want["contribution_profit"])) <= 0.50
    # February: business FAIL still published
    assert oracle_kpi()["2026-02"]["revenue_status"] == "FAIL"


def test_17_mlops_evidence_runs_are_additive_and_never_touch_forecasts(env):
    """Historical evaluation / experiment tickets read published warehouses only: sealed forecasts and published actuals stay byte-identical."""
    def snapshot():
        return (q("SELECT forecast_run_id::text,status,is_official,sealed_at FROM demo_ml.forecast_run ORDER BY 1"),
                q("SELECT forecast_run_id::text,product_group_id,predicted_net_revenue FROM demo_ml.forecast_result ORDER BY 1,2"),
                q('SELECT COUNT(*) FROM demo_er1."Fact_Order_Items"')[0][0], q("SELECT COUNT(*) FROM demo_ml.scenario_decision")[0][0])
    before = snapshot()
    assert fc("POST", "mlops_run", body={"month": "2026-07", "kind": "OFFICIAL_LINKED", "actor": "x"})[0] == 400      # only non-official kinds can be requested
    assert fc("POST", "mlops_run", body={"month": "2026-05", "kind": "HISTORICAL_EVALUATION", "actor": "x"})[0] == 409  # before the forecast gate
    assert fc("POST", "mlops_run", body={"month": "2026-07", "kind": "EXPERIMENT_ONLY"})[0] == 400                      # actor required
    results = {}
    for month, kind in (("2026-06", "HISTORICAL_EVALUATION"), ("2026-07", "HISTORICAL_EVALUATION"), ("2026-07", "EXPERIMENT_ONLY")):
        status, data = fc("POST", "mlops_run", body={"month": month, "kind": kind, "actor": "ml.tester"})
        assert status == 202, data
        assert data["post_hoc_actual"] is (kind == "HISTORICAL_EVALUATION")
        out = env["worker"].run_mlops(data["ticket"])
        assert out["status"] == "RECORDED" and out["summary"]["official_selection_changed"] is False
        results[(month, kind)] = out["summary"]
    again_status, again_ticket = fc("POST", "mlops_run", body={"month": "2026-06", "kind": "HISTORICAL_EVALUATION", "actor": "ml.tester"})
    assert again_status == 202                                            # (the API harness has no object store; the worker is the idempotency authority)
    repeat = env["worker"].run_mlops(again_ticket["ticket"])
    assert repeat["summary"]["mlops"]["status"] == "ALREADY_RECORDED" and repeat["summary"]["mlops"]["training_run_id"] == results[("2026-06", "HISTORICAL_EVALUATION")]["mlops"]["training_run_id"]
    june = results[("2026-06", "HISTORICAL_EVALUATION")]["mlops"]
    july = results[("2026-07", "HISTORICAL_EVALUATION")]["mlops"]
    assert june["evaluation_status"] == "EXPERIMENTAL_INSUFFICIENT_VALIDATION" and july["evaluation_status"] == "ELIGIBLE"
    stored = {key: data for (_b, key), data in env["s3"].objects.items()}
    for run in (june, july):
        for name in ("run", "evaluation", "params", "report", "drift", "status", "features_used"):
            assert f"{run['run_path']}/{name}.json" in stored
    drift = json.loads(stored[f"{june['run_path']}/drift.json"])
    assert drift["auto_retrain"] is False and drift["sealed_forecast_modified"] is False and drift["performance_drift"]["status"] == "INSUFFICIENT_EVIDENCE"
    report = json.loads(stored[f"{june['run_path']}/report.json"])
    assert report["forecast_vs_actual"]["actual_shop"] is not None and report["official_selection"]["ridge_marketing_in_selection"] is False
    exp = results[("2026-07", "EXPERIMENT_ONLY")]["mlops"]
    assert any(key.startswith("vercel-lab/ml/index/EXPERIMENT_ONLY/2026-07/") for key in stored) and exp["training_run_id"]
    assert snapshot() == before


def test_18_champion_challenger_monitoring_is_automatic_pre_actual_and_isolated(env):
    objects = {key: data for (_b, key), data in env["s3"].objects.items()}
    status = env["ctx"]["monitoring_status"]
    assert status["2026-07"]["status"] == "EVALUATED" and status["2026-08"]["status"] == "EVALUATED" and status["2026-10"]["status"] == "EVALUATED"
    assert status["2026-09"]["status"] == "FAILED" and "injected" in status["2026-09"]["error"]          # failure is reported, publish was SUCCESS (asserted in test 16)
    cycle = q("SELECT cycle_number FROM demo_control.dataset_state")[0][0]
    base = f"vercel-lab/ml/monitoring/lab-cycle-{cycle}"
    evals = {k.rsplit("/", 1)[1][:-5]: json.loads(v) for k, v in objects.items() if k.startswith(f"{base}/evaluations/")}
    assert sorted(evals) == ["2026-06", "2026-07", "2026-08", "2026-10"]                                  # September was not recorded: not guessed afterwards
    summaries = sorted(k for k in objects if k.startswith(f"{base}/summary/"))
    assert summaries[-1].endswith("through=2026-10.json")
    summary = json.loads(objects[summaries[-1]])
    assert summary["counted_months"] == 4 and summary["evidence_level"] == "PRELIMINARY"
    assert summary["recommendation"]["status"] == "PRELIMINARY_NOT_ASSESSED" and summary["recommendation"]["auto_switch_champion"] is False
    # June: the shadow counted is the one bound to the SEALED forecast, not the second (unsealed) draft generated in test 13
    sealed_id = env["ctx"]["june_draft"]["forecast_run_id"]
    pointer = json.loads(objects[f"vercel-lab/ml/monitoring/by_forecast/{sealed_id}.json"])
    assert evals["2026-06"]["shadow_training_run_id"] == pointer["training_run_id"] and evals["2026-06"]["official_forecast_id"] == sealed_id
    # independent oracle: actual comes from the QA file; champion = the SEALED official baseline of each month (read back through the API); ML = stored shadow
    oracle = oracle_groups()
    sealed_by_month = {m: fc("GET", "forecast", {"month": m})[1]["official"] for m in evals}
    assert all(o["method_type"] == "BASELINE" for o in sealed_by_month.values())
    for key in ("baseline", "ml"):
        err = act = 0.0
        for month, ev in evals.items():
            shadow = json.loads(objects[f"vercel-lab/ml/runs/{ev['shadow_training_run_id']}/shadow_forecast.json"])
            assert shadow["kind"] == "OFFICIAL_LINKED" and shadow["created_at"] < ev["actual_published_at"]    # recorded before the actual was published
            assert shadow["target_month"] == month and shadow["data_cutoff"] < month + "-01" and shadow["feature_version"] and shadow["ml"]["model_version"]
            if key == "baseline":
                official = sealed_by_month[month]
                assert ev["champion_model"] == "baseline_" + official["model_name"]
                assert shadow["baselines"][ev["champion_model"]]["shop"] == pytest.approx(official["shop_forecast"], abs=0.02)    # shadow baseline == sealed official
                predicted = official["shop_forecast"]
            else:
                predicted = shadow["ml"]["shop"]
            err += abs(predicted - sum(oracle[month].values()))
            act += sum(oracle[month].values())
        assert summary["cumulative"][key]["wape_pct"] == pytest.approx(100 * err / act, abs=0.05)
    assert summary["data_origin"] == "LOCAL_REAL_SOURCE_TEST" and summary["stream"] == f"lab-cycle-{cycle}"
    assert summary["champion_models_by_month"] == {m: "baseline_" + o["model_name"] for m, o in sealed_by_month.items()}
    # the sealed June official forecast is exactly what it was when it was sealed
    june = fc("GET", "forecast", {"month": "2026-06"})[1]["official"]
    assert june["results"] == env["ctx"]["june_sealed"]["results"] and str(june["sealed_at"]) == env["ctx"]["june_sealed"]["sealed_at"]
    assert june["forecast_run_id"] == env["ctx"]["june_sealed"]["forecast_run_id"] and june["method_type"] == "BASELINE"
    assert q("SELECT DISTINCT method_type FROM demo_ml.forecast_run") == [("BASELINE",)]               # no ML forecast row exists, sealed or draft
    assert set(summary["cumulative"]["groups"]) == {"PG01", "PG02", "PG03", "PG04", "PG05"}
    # historical evaluations / experiments created after the actuals (test 17) never entered the monitoring
    hist_ids = {json.loads(v)["training_run_id"] for k, v in objects.items() if "/index/HISTORICAL_EVALUATION/" in k or "/index/EXPERIMENT_ONLY/" in k}
    assert hist_ids and not hist_ids & {ev["shadow_training_run_id"] for ev in evals.values()}
    assert q("SELECT COUNT(*) FROM demo_ml.forecast_run WHERE is_official")[0][0] == 5 and q("SELECT COUNT(*) FROM demo_control.published_snapshot")[0][0] == 10
    out = os.environ.get("DQ_TEST_ML_DIR")
    if out:                                                                                         # artifacts for the UI check (real pipeline output)
        for key, data in objects.items():
            if key.startswith("vercel-lab/ml/"):
                target = Path(out) / key[len("vercel-lab/"):]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        (Path(out) / "cycle.txt").write_text(str(cycle))


def test_19_concurrent_monitoring_writers_are_serialised_by_the_stream_lock(env, tmp_path):
    import threading
    from pipeline.mlops import locks, monitoring as mon
    from pipeline.mlops.store import LocalDirStore
    from tests.test_mlops_monitoring import actual_rows_for, official_from, real_shadow_store

    class SlowStore(LocalDirStore):                                    # widens the check-then-write window the real object store has
        def put(self, key, data):
            time.sleep(0.25)
            super().put(key, data)

    def race(stream, locked):
        _rows, b, _store, _out = real_shadow_store(tmp_path / ("a" if locked else "b"))
        store = SlowStore(tmp_path / ("a" if locked else "b"))
        pub = (datetime.fromisoformat(b["shadow"]["created_at"]) + timedelta(minutes=1)).isoformat()
        results, barrier = [], threading.Barrier(4)

        def work():
            barrier.wait()
            try:
                kw = dict(stream=stream, cycle=1, month="2026-06", forecast=official_from(b, "fc-real"), actual_rows=actual_rows_for("2026-06"), actual_published_at=pub, actual_run_id="r")
                if locked:
                    with locks.stream_lock(DB_URL, stream):
                        results.append(mon.record_month(store, **kw)["status"])
                else:
                    results.append(mon.record_month(store, **kw)["status"])
            except Exception as error:
                results.append(type(error).__name__)
        threads = [threading.Thread(target=work) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        return sorted(results)
    assert race("race-locked", True) == ["ALREADY_RECORDED"] * 3 + ["EVALUATED"]                         # exactly one writer wins, the rest see it
    assert race("race-open", False) != ["ALREADY_RECORDED"] * 3 + ["EVALUATED"]                         # without the lock the race is real (why the lock exists)


def test_20_a_failed_monitoring_month_is_recovered_from_the_original_evidence(env):
    """September's monitoring was killed in test 16. Recovery evaluates it from the sealed Official + the shadow recorded BEFORE the actual was published."""
    cycle = q("SELECT cycle_number FROM demo_control.dataset_state")[0][0]
    base = f"vercel-lab/ml/monitoring/lab-cycle-{cycle}"
    snap = lambda: {key: data for (_b, key), data in env["s3"].objects.items()}
    before_objects = snap()
    assert f"{base}/evaluations/2026-09.json" not in before_objects
    forecasts_before = (q("SELECT forecast_run_id::text,status,is_official,sealed_at FROM demo_ml.forecast_run ORDER BY 1"),
                        q("SELECT forecast_run_id::text,product_group_id,predicted_net_revenue FROM demo_ml.forecast_result ORDER BY 1,2"))
    status, ticket = fc("POST", "monitoring_repair", body={})
    assert status == 202 and ticket["ticket"]
    out = env["worker"].run_monitoring_repair(ticket["ticket"])["summary"]["repair"]
    assert out["evaluated"] == ["2026-09"] and out["latest_summary_through"] == "2026-10"
    after = snap()
    new_keys = sorted(set(after) - set(before_objects))
    assert new_keys == [f"{base}/evaluations/2026-09.json", f"{base}/summary/through=2026-10.rev1.json"]   # only the missing evaluation and a new summary revision
    assert all(after[k] == v for k, v in before_objects.items())                                         # nothing existing was rewritten
    row = json.loads(after[f"{base}/evaluations/2026-09.json"])
    sept_run = q("SELECT finished_at FROM demo_control.pipeline_runs WHERE result_summary->>'batch'='incremental_08' AND status='SUCCEEDED'")[0][0]
    assert row["status"] == "EVALUATED" and row["data_origin"] == "LOCAL_REAL_SOURCE_TEST"
    assert datetime.fromisoformat(row["actual_published_at"]) == sept_run                                  # original publish time, not the time of the retry
    assert row["shadow_created_at"] < row["actual_published_at"]
    oracle = oracle_groups()["2026-09"]
    assert row["actual"]["shop"] == pytest.approx(sum(oracle.values()), abs=0.1)
    old_summary = json.loads(after[f"{base}/summary/through=2026-10.json"])
    new_summary = json.loads(after[f"{base}/summary/through=2026-10.rev1.json"])
    assert old_summary["counted_months"] == 4 and new_summary["counted_months"] == 5                       # history kept, newest revision is complete
    assert [m["month"] for m in new_summary["monthly"]] == ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    status2, ticket2 = fc("POST", "monitoring_repair", body={})                                           # a second recovery changes nothing and counts nothing twice
    out2 = env["worker"].run_monitoring_repair(ticket2["ticket"])["summary"]["repair"]
    assert out2["evaluated"] == [] and out2["summary_repaired"] == [] and snap() == after
    assert forecasts_before == (q("SELECT forecast_run_id::text,status,is_official,sealed_at FROM demo_ml.forecast_run ORDER BY 1"),
                                q("SELECT forecast_run_id::text,product_group_id,predicted_net_revenue FROM demo_ml.forecast_result ORDER BY 1,2"))
    assert q("SELECT DISTINCT method_type FROM demo_ml.forecast_run") == [("BASELINE",)]
