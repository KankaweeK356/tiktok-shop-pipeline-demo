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
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from .orchestrator import STAGES

REQUIRED_PHASE = {"RUN1": "EMPTY", "RUN2": ("RUN1_READY","RUN2_READY"), "REPLAY": "RUN2_READY"}
NEXT_PHASE = {"RUN1": "RUN1_READY", "RUN2": "RUN2_READY", "REPLAY": "RUN2_READY"}


def begin_run(database_url: str, run_type: str) -> str:
    if run_type not in REQUIRED_PHASE:
        raise ValueError("Only RUN1, RUN2, REPLAY are allowed in live demo")
    run_id = str(uuid4())
    run_number = os.getenv("GITHUB_RUN_ID","local")
    attempt = os.getenv("GITHUB_RUN_ATTEMPT","1")
    request_key = f"github-{run_number}-{attempt}-{run_type.lower()}"
    repo = os.getenv("GITHUB_REPOSITORY","KankaweeK356/tiktok-shop-pipeline-demo")
    runner_ref = (f"https://github.com/{repo}/actions/runs/{run_number}"
                  if run_number != "local" else "local-run")
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            cur.execute("SELECT phase,cycle_number FROM demo_control.dataset_state "
                        "WHERE dataset_key='classroom' FOR UPDATE")
            row = cur.fetchone()
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
                VALUES (%s,'classroom',%s,%s,%s,'RUNNING',%s,'github-actions',now(),
                   '{"recorded_live":true}'::jsonb)
            """,(run_id,cycle,run_type,request_key,runner_ref))
    return run_id


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
                 result: dict, workspace: Path) -> None:
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
                     "run_type":run_type,"batch":batch,
                     "paid_items":result.get("paid_sales_rows"),
                     "net_revenue":result.get("net_revenue"),
                     "replay_idempotent":True if run_type=="REPLAY" else None,
                     "stage_count":len(STAGES)}
            cur.execute("""
                UPDATE demo_control.pipeline_runs
                   SET status='SUCCEEDED',finished_at=now(),result_summary=%s
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
                "note":"See GitHub Actions logs for sanitized error evidence"
            }),run_id))
            if failed_stage:
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
