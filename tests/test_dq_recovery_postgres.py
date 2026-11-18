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
    env["ctx"]["june_draft"] = draft


def test_13_seal_once_is_immutable_and_unlocks_june(env):
    draft = env["ctx"]["june_draft"]
    status, bad = fc("POST", "seal", body={"forecast_run_id": draft["forecast_run_id"]})
    assert status == 400                                   # actor required
    other = forecast_for(env, "2026-06")                   # drafts may be retried; only one can ever become official
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


def test_16_rolling_july_to_october_every_month_forecast_sealed_before_actual(env):
    for month, batch in (("2026-07", "incremental_06"), ("2026-08", "incremental_07"), ("2026-09", "incremental_08"), ("2026-10", "incremental_09")):
        with pytest.raises(RuntimeError) as locked:                   # the gate cannot be bypassed
            run_month(env, batch)
        assert "LAB_FORECAST_NOT_SEALED" in str(locked.value)
        draft = forecast_for(env, month)
        previous = f"2026-{int(month[5:]) - 1:02d}"
        assert draft["published_through"] == previous                  # only data through the previous month
        assert fc("POST", "seal", body={"forecast_run_id": draft["forecast_run_id"], "actor": "business.owner"})[0] == 200
        sealed_at = q("SELECT sealed_at FROM demo_ml.forecast_run WHERE forecast_run_id=%s", (draft["forecast_run_id"],))[0][0]
        assert run_month(env, batch)["summary"]["status"] == "SUCCESS"
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
