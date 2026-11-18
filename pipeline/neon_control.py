"""Authoritative Neon control state for future classroom runs (never resets data).

Persists RUNNING/SUCCEEDED/FAILED, per-stage validation and actual stage log
timestamps. The previous classroom run is separately marked as a historical
backfill and is not passed through this live recorder.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from .orchestrator import STAGES

REQUIRED_PHASE = {"RUN1": "EMPTY", "RUN2": ("RUN1_READY","RUN2_READY"), "REPLAY": "RUN2_READY"}
NEXT_PHASE = {"RUN1": "RUN1_READY", "RUN2": "RUN2_READY", "REPLAY": "RUN2_READY"}


def begin_run(database_url: str, run_type: str, *, batch: str | None = None,
              expected_cycle: int | None = None) -> str:
    if run_type not in REQUIRED_PHASE:
        raise ValueError("Only RUN1, RUN2, REPLAY are allowed in live demo")
    engine = os.getenv("CLASSROOM_EXECUTION_ENGINE", "GITHUB_ACTIONS")
    run_id = str(UUID(os.environ["CLASSROOM_RUN_ID"])) if engine == "VERCEL_NATIVE" and os.getenv("CLASSROOM_RUN_ID") else str(uuid4())
    run_number = os.getenv("GITHUB_RUN_ID", "local")
    attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
    request_key = (f"vercel-{run_id}" if engine == "VERCEL_NATIVE"
                   else f"github-{run_number}-{attempt}-{run_type.lower()}")
    repo = os.getenv("GITHUB_REPOSITORY","KankaweeK356/tiktok-shop-pipeline-demo")
    runner_ref = (f"https://{os.getenv('VERCEL_URL')}" if engine == "VERCEL_NATIVE" and
                  os.getenv("VERCEL_URL") else
                  f"https://github.com/{repo}/actions/runs/{run_number}"
                  if engine != "VERCEL_NATIVE" and run_number != "local" else engine)
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            if expected_cycle is None:
                cur.execute("SELECT phase,cycle_number FROM demo_control.dataset_state "
                            "WHERE dataset_key='classroom' FOR UPDATE")
            else:
                cur.execute("SELECT phase,cycle_number FROM demo_control.dataset_state "
                            "WHERE dataset_key='classroom' AND cycle_number=%s FOR UPDATE",
                            (expected_cycle,))
            row = cur.fetchone()
            if expected_cycle is not None and not row:
                raise RuntimeError("CYCLE_CHANGED: Lab was cleared or advanced before this run started")
            allowed=REQUIRED_PHASE[run_type]
            if not row or row[0] not in (allowed if isinstance(allowed,tuple) else (allowed,)):
                raise RuntimeError(f"{run_type}: wrong phase; expected {REQUIRED_PHASE[run_type]}")
            phase,cycle=row
            cur.execute("SELECT COUNT(*) FROM demo_control.pipeline_runs "
                        "WHERE dataset_key='classroom' AND status IN ('RUNNING','QUEUED')")
            if cur.fetchone()[0]:
                raise RuntimeError("Another Neon demo operation is in progress")
            cur.execute("""
                INSERT INTO demo_control.pipeline_runs
                 (run_id,dataset_key,cycle_number,run_type,request_key,
                  status,runner_ref,triggered_by,started_at,result_summary)
                VALUES (%s,'classroom',%s,%s,%s,'RUNNING',%s,%s,now(),%s::jsonb)
            """,(run_id,cycle,run_type,request_key,runner_ref,
                 "vercel-web" if engine == "VERCEL_NATIVE" else "github-actions",
                 Jsonb({"recorded_live":True,"execution_engine":engine,
                        "batch":batch,"active_stage":None})))
    return run_id


def mark_stage_started(database_url: str, run_id: str, stage: str) -> None:
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            cur.execute("""
                INSERT INTO demo_control.stage_runs(run_id,stage_name,status,metrics)
                VALUES (%s,%s,'RUNNING',%s)
                ON CONFLICT (run_id,stage_name) DO UPDATE
                  SET status='RUNNING',finished_at=NULL,metrics=EXCLUDED.metrics
            """, (run_id, stage, Jsonb({"execution_engine":os.getenv(
                "CLASSROOM_EXECUTION_ENGINE", "GITHUB_ACTIONS")})))
            cur.execute("""
                UPDATE demo_control.pipeline_runs
                   SET result_summary=COALESCE(result_summary,'{}'::jsonb) ||
                       jsonb_build_object('active_stage',%s::text)
                 WHERE run_id=%s AND status='RUNNING'
            """, (stage, run_id))


def complete_stage(database_url: str, run_id: str, stage: str, result: dict) -> None:
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            cur.execute("""
                INSERT INTO demo_control.stage_runs(run_id,stage_name,status,finished_at,metrics)
                VALUES (%s,%s,'SUCCESS',now(),%s)
                ON CONFLICT (run_id,stage_name) DO UPDATE
                  SET status='SUCCESS',finished_at=now(),metrics=EXCLUDED.metrics
            """, (run_id, stage, Jsonb({"result":result,"recorded_live":True})))


def _stage_log_records(workspace: Path, batch: str):
    path=Path(workspace)/"lake"/"control"/"stage_history.jsonl"
    if not path.is_file(): return {}
    records={}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        item=json.loads(line)
        if item.get("batch")==batch and item.get("stage") in STAGES:
            records[item["stage"]]=item
    return records


def complete_run(database_url: str, run_id: str, run_type: str,
                 result: dict, workspace: Path, *, artifact_uri: str | None = None) -> None:
    if result.get("status")!="SUCCESS":
        raise ValueError("A non-successful batch cannot complete a Neon run")
    batch = result.get("batch") or {"RUN1":"initial","RUN2":"incremental_01","REPLAY":"incremental_01"}[run_type]
    stage_logs = _stage_log_records(workspace,batch)
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            cur.execute("SELECT status FROM demo_control.pipeline_runs WHERE run_id=%s FOR UPDATE",
                        (run_id,))
            if cur.fetchone() != ("RUNNING",):
                raise RuntimeError("Run does not exist or is not RUNNING")
            for stage in STAGES:
                if run_type=="REPLAY":
                    status="SKIPPED"
                    detail={"reason":"COMPLETED_BATCH_CHECKPOINT_REPLAY",
                            "no_reprocessing":True}
                    event_at=None
                else:
                    item=stage_logs.get(stage)
                    if not item or item["status"]!="SUCCESS":
                        raise RuntimeError(f"Missing successful stage evidence: {stage}")
                    status="SUCCESS"
                    detail={"elapsed_seconds":item.get("elapsed_seconds"),
                            "result":result.get("metrics",{}).get(stage,{}).get("result",{}),
                            "recorded_live":True}
                    event_at=datetime.fromisoformat(item["at"])
                cur.execute("""
                    INSERT INTO demo_control.stage_runs
                       (run_id,stage_name,status,finished_at,metrics)
                    VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT (run_id,stage_name) DO UPDATE
                       SET status=EXCLUDED.status,finished_at=EXCLUDED.finished_at,
                           metrics=EXCLUDED.metrics
                """,(run_id,stage,status,event_at,Jsonb(detail)))
                cur.execute("""
                    INSERT INTO demo_control.stage_events
                       (run_id,stage_name,event_type,occurred_at,message,details)
                    VALUES (%s,%s,%s,COALESCE(%s,now()),%s,%s)
                """,(run_id,stage,
                    "SUCCEEDED" if status=="SUCCESS" else "SKIPPED",
                    event_at,"Recorded automatically during live Neon demo",
                    Jsonb({"recorded_live":True,"replay":run_type=="REPLAY"})))
            summary={"recorded_live":True,"source":"NEON_POSTGRESQL",
                     "execution_engine":os.getenv("CLASSROOM_EXECUTION_ENGINE", "GITHUB_ACTIONS"),
                     "run_type":run_type,"batch":batch,
                     "paid_items":result.get("paid_sales_rows"),
                     "net_revenue":result.get("net_revenue"),
                     "replay_idempotent":True if run_type=="REPLAY" else None,
                     "stage_count":len(STAGES),"active_stage":None}
            cur.execute("""
                UPDATE demo_control.pipeline_runs
                   SET status='SUCCEEDED',finished_at=now(),
                       result_summary=COALESCE(result_summary,'{}'::jsonb) || %s::jsonb
                 WHERE run_id=%s
                """,(Jsonb(summary),run_id))
            cur.execute("""
                UPDATE demo_control.dataset_state
                   SET phase=%s,last_run_id=%s,lock_version=lock_version+1,updated_at=now()
                 WHERE dataset_key='classroom' AND phase=%s
            """,(NEXT_PHASE[run_type],run_id,"EMPTY" if run_type=="RUN1" else
                 "RUN2_READY" if run_type=="REPLAY" or batch!="incremental_01" else "RUN1_READY"))
            if cur.rowcount!=1:
                raise RuntimeError("Neon phase changed while completing run")
            if run_type != "REPLAY":
                _publish_snapshot(cur, run_id, batch, artifact_uri)


def fail_run(database_url: str, run_id: str, run_type: str,
             workspace: Path, error: BaseException, *, batch: str | None = None) -> None:
    if batch is None:
        batch="initial" if run_type=="RUN1" else "incremental_01"
    stage_logs=_stage_log_records(workspace,batch)
    # Do not serialize database connection strings or exception internals into logs.
    failed_stage=next((stage for stage in STAGES
                       if stage_logs.get(stage,{}).get("status")=="FAILED"),None)
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            cur.execute("""
                UPDATE demo_control.pipeline_runs SET status='FAILED',finished_at=now(),
                  error_message=%s,result_summary=%s
                WHERE run_id=%s AND status='RUNNING'
            """,(type(error).__name__,Jsonb({
                "recorded_live":True,"failed_stage":failed_stage,
                "batch":batch,
                "error_code":stage_logs.get(failed_stage,{}).get("error_code") if failed_stage else type(error).__name__,
                "failure_class":"SYSTEM",
                "note":"Inspect the Vercel run result for sanitized stage evidence"
            }),run_id))
            run_was_active = cur.rowcount == 1
            if failed_stage and run_was_active:
                item=stage_logs[failed_stage]
                cur.execute("""
                    INSERT INTO demo_control.stage_runs(run_id,stage_name,status,metrics)
                    VALUES (%s,%s,'FAILED',%s)
                    ON CONFLICT (run_id,stage_name)
                    DO UPDATE SET status='FAILED',metrics=EXCLUDED.metrics
                """,(run_id,failed_stage,Jsonb({
                    "error_code":item.get("error_code"),
                    "recorded_live":True})))
                cur.execute("""
                    INSERT INTO demo_control.stage_events(run_id,stage_name,event_type,details)
                    VALUES (%s,%s,'FAILED',%s)
                """,(run_id,failed_stage,Jsonb({
                    "error_code":item.get("error_code"),
                    "recorded_live":True})))


# --------------------------------------------------------------------------
# Data-quality recovery support (additive; every function degrades gracefully
# when the DQ migration has not been applied to the target Neon branch yet).
# --------------------------------------------------------------------------

DQ_TABLE = "demo_control.dq_issue"


def _has_dq(cur) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (DQ_TABLE,))
    return bool(cur.fetchone()[0])


def dq_schema_ready(database_url: str) -> bool:
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            return _has_dq(cur)


def record_source_identity(database_url: str, run_id: str, identity: dict) -> None:
    """Persist exactly which Source ZIP (version + SHA-256) this run consumed."""
    compact = {k: identity.get(k) for k in (
        "source_version", "lock_status", "origin", "uri", "batch", "month",
        "zip_sha256", "zip_bytes", "dataset_version")}
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            cur.execute("""
                UPDATE demo_control.pipeline_runs
                   SET result_summary=COALESCE(result_summary,'{}'::jsonb) ||
                       jsonb_build_object('source_identity',%s::jsonb,'source_version',%s::text)
                 WHERE run_id=%s AND status='RUNNING'
            """, (Jsonb(compact), identity.get("source_version"), run_id))
            cur.execute("""
                INSERT INTO demo_control.pipeline_artifacts
                   (run_id,stage_name,artifact_type,artifact_uri,content_sha256,size_bytes)
                VALUES (%s,'ingest','SOURCE',%s,%s,%s)
                ON CONFLICT (run_id,artifact_type,artifact_uri) DO NOTHING
            """, (run_id, identity.get("uri") or identity.get("origin") or "unknown",
                  identity.get("zip_sha256"), identity.get("zip_bytes")))


def previous_source_version(database_url: str, cycle: int) -> str | None:
    """Source version of the latest successful run of the cycle (None = no run yet)."""
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            cur.execute("""
                SELECT COALESCE(result_summary->>'source_version','classroom-source-v1')
                  FROM demo_control.pipeline_runs
                 WHERE dataset_key='classroom' AND cycle_number=%s AND status='SUCCEEDED'
                 ORDER BY finished_at DESC NULLS LAST, started_at DESC LIMIT 1
            """, (cycle,))
            row = cur.fetchone()
    return row[0] if row else None


def _run_scope(cur, run_id: str):
    cur.execute("SELECT dataset_key,cycle_number FROM demo_control.pipeline_runs WHERE run_id=%s", (run_id,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError("Run does not exist")
    return row


def _insert_rule_results(cur, run_id, dataset, cycle, batch, stage, report):
    rows = []
    for r in report["results"]:
        rows.append((run_id, dataset, cycle, batch, stage, r["evaluation_kind"], r["rule_id"],
                     r["rule_name"], r["rule_kind"], r["input_table"], r["input_column"],
                     r["checked_rows"], r["failed_rows"], r["threshold"], r["severity"], r["status"],
                     report["source"].get("zip_sha256"), r["source_file"], r["source_file_sha256"],
                     report.get("correction_set_id")))
    cur.executemany("""
        INSERT INTO demo_control.dq_rule_result
          (run_id,dataset_key,cycle_number,batch,stage_name,evaluation_kind,rule_id,rule_name,rule_kind,
           input_table,input_column,checked_rows,failed_rows,threshold,severity,status,
           source_zip_sha256,source_file,source_file_sha256,correction_set_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, rows)


def record_dq_results(database_url: str, run_id: str, workspace: Path, batch: str, stage: str) -> bool:
    """Persist PASS/FAIL/NOT_CHECKED results of a stage that completed (GATE/DEFENSE)."""
    kind = {"ingest": "gate", "transform": "defense"}.get(stage)
    if not kind:
        return False
    path = Path(workspace) / "lake" / "governance" / "dq" / f"{batch}_{stage}_{kind}_report.json"
    if not path.is_file():
        return False
    report = json.loads(path.read_text(encoding="utf-8"))
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            if not _has_dq(cur):
                return False
            dataset, cycle = _run_scope(cur, run_id)
            cur.execute("DELETE FROM demo_control.dq_rule_result WHERE run_id=%s AND stage_name=%s "
                        "AND evaluation_kind=%s", (run_id, stage, report["evaluation_kind"]))
            _insert_rule_results(cur, run_id, dataset, cycle, batch, stage, report)
    return True


def block_run(database_url: str, run_id: str, run_type: str, workspace: Path,
              error: BaseException, *, batch: str, stage: str = "ingest") -> dict:
    """Persist a BLOCKING data-quality failure: rule results + durable issues + BLOCKED_DQ.

    Falls back to the legacy FAILED record when the DQ migration is not present yet,
    so a not-yet-migrated branch never loses the failure."""
    report = getattr(error, "report", None)
    if report is None:
        raise ValueError("block_run requires a DQBlocked error with a report")
    bucket = os.getenv("CLASSROOM_STORAGE_BUCKET", "")
    evidence = f"s3://{bucket}/vercel-lab/blocked/{run_id}/dq_report.json" if bucket else None
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            if not _has_dq(cur):
                persisted = False
            else:
                persisted = True
                dataset, cycle = _run_scope(cur, run_id)
                _insert_rule_results(cur, run_id, dataset, cycle, batch, stage, report)
                for issue in report["issues"]:
                    cur.execute("""
                        INSERT INTO demo_control.dq_issue
                          (issue_key,dataset_key,cycle_number,batch,first_run_id,last_run_id,rule_id,severity,
                           table_name,source_file,source_file_sha256,source_zip_sha256,source_row_no,pk_json,
                           column_name,invalid_value,parent_table,parent_column,row_snapshot,context,evidence_uri)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (dataset_key,cycle_number,issue_key) DO UPDATE
                           SET last_run_id=EXCLUDED.last_run_id, updated_at=now(),
                               status=CASE WHEN demo_control.dq_issue.status IN ('CORRECTED','REVALIDATED')
                                           THEN 'OPEN' ELSE demo_control.dq_issue.status END
                    """, (issue["issue_key"], dataset, cycle, batch, run_id, run_id, issue["rule_id"],
                          issue["severity"], issue["table"], issue["source_file"],
                          issue["source_file_sha256"], issue["source_zip_sha256"], issue["source_row_no"],
                          Jsonb(issue["pk"]), issue["column"],
                          None if issue["invalid_value"] is None else str(issue["invalid_value"]),
                          issue.get("parent_table"), issue.get("parent_column"),
                          Jsonb(issue["row_snapshot"], dumps=lambda v: json.dumps(v, default=str)),
                          Jsonb(issue.get("context") or {}, dumps=lambda v: json.dumps(v, default=str)),
                          evidence))
            code = "DQ_BLOCKED"
            summary = {"recorded_live": True, "failed_stage": stage, "batch": batch,
                       "error_code": code, "failure_class": "DATA_QUALITY",
                       "issue_count": len(report["issues"]),
                       "blocking_failed_rules": report["summary"]["blocking_failed_rules"],
                       "dq_persisted": persisted, "dq_evidence_uri": evidence}
            new_status = "BLOCKED_DQ" if persisted else "FAILED"
            cur.execute("""
                UPDATE demo_control.pipeline_runs
                   SET status=%s, finished_at=now(), error_message=%s,
                       result_summary=COALESCE(result_summary,'{}'::jsonb) || %s::jsonb
                 WHERE run_id=%s AND status='RUNNING'
            """, (new_status, code, Jsonb(summary), run_id))
            cur.execute("""
                INSERT INTO demo_control.stage_runs(run_id,stage_name,status,metrics)
                VALUES (%s,%s,'FAILED',%s)
                ON CONFLICT (run_id,stage_name) DO UPDATE SET status='FAILED',metrics=EXCLUDED.metrics
            """, (run_id, stage, Jsonb({"error_code": code, "failure_class": "DATA_QUALITY",
                                         "issue_count": len(report["issues"]), "recorded_live": True})))
            cur.execute("""
                INSERT INTO demo_control.stage_events(run_id,stage_name,event_type,details)
                VALUES (%s,%s,'FAILED',%s)
            """, (run_id, stage, Jsonb({"error_code": code, "failure_class": "DATA_QUALITY",
                                         "issue_count": len(report["issues"])})))
    return {"persisted": persisted, "status": new_status, "evidence_uri": evidence, **summary}


def load_correction_context(database_url: str, cycle: int, batch: str, zip_sha256: str) -> dict:
    """Approved corrections + latest revalidation for this batch/source (empty if no DQ schema)."""
    empty = {"correction_set_id": None, "corrections": [], "has_issues": False,
             "revalidated": False, "open_issues": 0}
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            if not _has_dq(cur):
                return empty
            cur.execute("""
                SELECT COUNT(*) FILTER (WHERE status IN ('OPEN','CORRECTED','REVALIDATED')),
                       COUNT(*) FILTER (WHERE status='OPEN'), COUNT(*)
                  FROM demo_control.dq_issue
                 WHERE dataset_key='classroom' AND cycle_number=%s AND batch=%s AND source_zip_sha256=%s
            """, (cycle, batch, zip_sha256))
            unresolved, opened, total = cur.fetchone()
            cur.execute("""
                SELECT correction_id::text,issue_id::text,version,table_name,pk_json,column_name,
                       original_value,corrected_value
                  FROM demo_control.dq_effective_correction
                 WHERE dataset_key='classroom' AND cycle_number=%s AND batch=%s AND source_zip_sha256=%s
                 ORDER BY issue_id
            """, (cycle, batch, zip_sha256))
            rows = cur.fetchall()
            cur.execute("SELECT demo_control.dq_correction_set_id('classroom',%s,%s,%s)",
                        (cycle, batch, zip_sha256))
            set_id = cur.fetchone()[0]
            cur.execute("""
                SELECT status,correction_set_id FROM demo_control.dq_revalidation
                 WHERE dataset_key='classroom' AND cycle_number=%s AND batch=%s AND source_zip_sha256=%s
                 ORDER BY executed_at DESC LIMIT 1
            """, (cycle, batch, zip_sha256))
            last = cur.fetchone()
    corrections = [{"correction_id": r[0], "issue_id": r[1], "version": r[2], "table": r[3],
                    "pk": r[4], "column": r[5], "original_value": r[6], "new_value": r[7]} for r in rows]
    return {"correction_set_id": set_id, "corrections": corrections, "has_issues": total > 0,
            "unresolved": unresolved, "open_issues": opened,
            "revalidated": bool(last and last[0] == "PASS" and last[1] == set_id)}


def require_revalidated(context: dict) -> None:
    """Resume gate: a previously blocked batch may only run after a PASSED revalidation
    of exactly the current correction set."""
    if context.get("unresolved", 0) and not context.get("revalidated"):
        raise RuntimeError("DQ_REVALIDATION_REQUIRED: apply and revalidate corrections before resuming")


def record_revalidation(database_url: str, cycle: int, batch: str, zip_sha256: str, report: dict,
                        correction_set_id: str | None, actor: str | None) -> dict:
    status = "FAIL" if report["summary"]["blocked"] else "PASS"
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            cur.execute("""
                INSERT INTO demo_control.dq_revalidation
                  (dataset_key,cycle_number,batch,blocked_run_id,correction_set_id,source_zip_sha256,
                   rules_executed,failed_rules,failed_rows,status,results,actor)
                VALUES ('classroom',%s,%s,
                        (SELECT run_id FROM demo_control.pipeline_runs
                          WHERE dataset_key='classroom' AND cycle_number=%s
                            AND status IN ('BLOCKED_DQ','READY_TO_RESUME')
                            AND result_summary->>'batch'=%s ORDER BY started_at DESC LIMIT 1),
                        %s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING reval_id::text
            """, (cycle, batch, cycle, batch, correction_set_id, zip_sha256,
                  report["summary"]["rules"], report["summary"]["blocking_failed_rules"],
                  report["summary"]["failed_rows"], status,
                  Jsonb({"results": report["results"], "issues": report["issues"],
                         "corrections_applied": report.get("corrections_applied", [])},
                        dumps=lambda v: json.dumps(v, default=str)), actor))
            reval_id = cur.fetchone()[0]
            if status == "PASS":
                cur.execute("""
                    UPDATE demo_control.dq_issue SET status='REVALIDATED', updated_at=now()
                     WHERE dataset_key='classroom' AND cycle_number=%s AND batch=%s
                       AND source_zip_sha256=%s AND status='CORRECTED'
                """, (cycle, batch, zip_sha256))
                cur.execute("""
                    UPDATE demo_control.pipeline_runs SET status='READY_TO_RESUME'
                     WHERE dataset_key='classroom' AND cycle_number=%s AND status='BLOCKED_DQ'
                       AND result_summary->>'batch'=%s
                """, (cycle, batch))
            else:
                cur.execute("""
                    UPDATE demo_control.dq_issue SET status='OPEN', updated_at=now()
                     WHERE dataset_key='classroom' AND cycle_number=%s AND batch=%s
                       AND source_zip_sha256=%s AND status IN ('CORRECTED','REVALIDATED')
                       AND issue_key = ANY(%s)
                """, (cycle, batch, zip_sha256, [i["issue_key"] for i in report["issues"]]))
    return {"reval_id": reval_id, "status": status, **report["summary"]}


def _publish_snapshot(cur, run_id: str, batch: str, artifact_uri: str | None) -> None:
    """Publish gate + lineage. Runs inside complete_run's transaction (all-or-nothing)."""
    if not _has_dq(cur):
        return
    dataset, cycle = _run_scope(cur, run_id)
    cur.execute("""
        SELECT COUNT(*) FROM demo_control.dq_issue
         WHERE dataset_key=%s AND cycle_number=%s AND batch=%s
           AND status IN ('OPEN','CORRECTED') AND severity='BLOCKING'
    """, (dataset, cycle, batch))
    if cur.fetchone()[0]:
        raise RuntimeError("PUBLISH_BLOCKED: unresolved BLOCKING data-quality issues")
    cur.execute("SELECT result_summary->'source_identity' FROM demo_control.pipeline_runs WHERE run_id=%s", (run_id,))
    source = cur.fetchone()[0] or {}
    zip_sha = source.get("zip_sha256")
    cur.execute("SELECT demo_control.dq_correction_set_id(%s,%s,%s,%s)", (dataset, cycle, batch, zip_sha))
    set_id = cur.fetchone()[0]
    cur.execute("UPDATE demo_control.published_snapshot SET is_current=false "
                "WHERE dataset_key=%s AND cycle_number=%s AND is_current", (dataset, cycle))
    cur.execute("""
        INSERT INTO demo_control.published_snapshot
          (dataset_key,cycle_number,batch,run_id,source_version,source_zip_sha256,correction_set_id,artifact_uri)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (dataset, cycle, batch, run_id, source.get("source_version"), zip_sha, set_id, artifact_uri))
    cur.execute("""
        UPDATE demo_control.dq_issue SET status='RESOLVED', resolved_run_id=%s, updated_at=now()
         WHERE dataset_key=%s AND cycle_number=%s AND batch=%s AND status='REVALIDATED'
           AND (%s::text IS NULL OR source_zip_sha256=%s)
    """, (run_id, dataset, cycle, batch, zip_sha, zip_sha))
    cur.execute("""
        UPDATE demo_control.pipeline_runs
           SET status='CANCELLED', result_summary=COALESCE(result_summary,'{}'::jsonb) ||
               jsonb_build_object('superseded_by',%s::text)
         WHERE dataset_key=%s AND cycle_number=%s AND status IN ('BLOCKED_DQ','READY_TO_RESUME')
           AND result_summary->>'batch'=%s AND run_id<>%s
    """, (run_id, dataset, cycle, batch, run_id))


# --------------------------------------------------------------------------
# Next-month forecast persistence (demo_ml; additive migration sql/neon_demo_ml_migration.sql)
# --------------------------------------------------------------------------
FORECAST_GATE_FROM = "2026-06"          # target months from June onward need a sealed official forecast
BATCH_BY_INDEX = ["initial"] + [f"incremental_{i:02d}" for i in range(1, 10)]


def batch_for_month(month: str) -> str:
    index = int(month[5:7]) - 1
    if month[:4] != "2026" or not 0 <= index < 10:
        raise ValueError("MONTH_OUT_OF_RANGE")
    return BATCH_BY_INDEX[index]


def month_for_batch(batch: str) -> str:
    return f"2026-{BATCH_BY_INDEX.index(batch) + 1:02d}"


def ml_schema_ready(database_url: str) -> bool:
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            cur.execute("SELECT to_regclass('demo_ml.forecast_run') IS NOT NULL")
            return bool(cur.fetchone()[0])


def require_sealed_forecast(database_url: str, cycle: int, batch: str) -> None:
    """Server-side gate: a target month from June on cannot be ingested without an OFFICIAL sealed forecast."""
    month = month_for_batch(batch)
    if month < FORECAST_GATE_FROM:
        return
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            cur.execute("SELECT to_regclass('demo_ml.forecast_run') IS NOT NULL")
            if not cur.fetchone()[0]:
                raise RuntimeError("LAB_FORECAST_SCHEMA_MISSING: demo_ml migration is not applied")
            cur.execute("""SELECT 1 FROM demo_ml.forecast_run
                            WHERE dataset_key='classroom' AND cycle_number=%s AND target_month=%s
                              AND is_official AND status='SEALED'""", (cycle, month + "-01"))
            if not cur.fetchone():
                raise RuntimeError(f"LAB_FORECAST_NOT_SEALED: seal the official forecast for {month} before running it")


def save_draft_forecast(database_url: str, cycle: int, source_run_id: str, result: dict, actor: str | None) -> str:
    from uuid import uuid4
    forecast_id = str(uuid4())
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            cur.execute("""
                INSERT INTO demo_ml.forecast_run
                  (forecast_run_id,dataset_key,cycle_number,target_month,training_cutoff_date,source_warehouse_run_id,
                   source_snapshot_sha256,method_type,model_name,model_version,feature_version,
                   baseline_validation_wape_pct,model_validation_wape_pct,validation_notes,selection_reason,created_by)
                VALUES (%s,'classroom',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (forecast_id, cycle, result["target_month"] + "-01", result["training_cutoff_date"], source_run_id,
                  result["source_snapshot_sha256"], result["method_type"], result["model_name"], result["model_version"],
                  result["feature_version"], result["baseline_validation_wape_pct"], result["model_validation_wape_pct"],
                  result["validation_notes"], result["selection_reason"], (actor or "CLASSROOM_DEMO")[:120]))
            cur.executemany("INSERT INTO demo_ml.forecast_result(forecast_run_id,product_group_id,predicted_net_revenue) "
                            "VALUES (%s,%s,%s)", [(forecast_id, g, v) for g, v in result["predictions"].items()])
    return forecast_id
