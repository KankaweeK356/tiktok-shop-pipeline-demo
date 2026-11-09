"""One *real* ETL stage per GitHub Actions run.

Previous workspace is restored from a GitHub Actions artifact by the workflow.
The same SQLite, Parquet, checkpoints and DuckDB files survive between jobs.
This cannot run against an already populated Neon cycle; explicit reset is required.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg

from .orchestrator import STAGES, run_batch
from .neon_control import begin_run, complete_run
from .schema import ROOT

STATE_PATH = ROOT / "output" / "classroom_lab" / "lab_session.json"


def _phase(db_url: str) -> tuple[str, int]:
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT phase,cycle_number FROM demo_control.dataset_state WHERE dataset_key='classroom'")
            value = cur.fetchone()
    if not value:
        raise RuntimeError("Neon demo control state is unavailable")
    return value


def run_stage(stage: str, batch: str) -> dict:
    if stage not in STAGES or batch not in ("initial", "incremental"):
        raise ValueError("Invalid stage or batch")
    db_url = os.getenv("NEON_DEMO_DATABASE_URL")
    if not db_url:
        raise RuntimeError("Protected Neon demo database secret is not configured")
    workspace = STATE_PATH.parent
    phase, cycle = _phase(db_url)
    required = "EMPTY" if batch == "initial" else "RUN1_READY"
    if phase != required:
        raise RuntimeError(
            f"Refusing live {batch} ETL in {phase} cycle {cycle}; "
            "do not reset existing data automatically"
        )
    index = STAGES.index(stage)
    if stage == "ingest":
        if STATE_PATH.exists() and batch == "initial":
            raise RuntimeError("Initial session exists; refuse duplicate ingest")
        if batch == "incremental":
            if not STATE_PATH.exists():
                raise RuntimeError("Initial workspace artifact is required for incremental")
            previous = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if previous.get("batch")!="initial" or previous.get("last_completed")!="validate":
                raise RuntimeError("Initial Validate must pass before Incremental")
        run_id = begin_run(db_url, "RUN1" if batch=="initial" else "RUN2")
        data = {"batch":batch,"cycle":cycle,"run_id":run_id,"last_completed":None}
    else:
        if not STATE_PATH.exists():
            raise RuntimeError("Missing previous stage checkpoint; restore GitHub artifact")
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if data.get("batch")!=batch or data.get("cycle")!=cycle:
            raise RuntimeError("Workspace batch/cycle mismatch")
        if data.get("last_completed")!=STAGES[index-1]:
            raise RuntimeError("Step order violated; expected "+STAGES[index-1])
    result=run_batch(workspace,batch,stop_after=stage)
    if stage!="validate" and result.get("status")!="PARTIAL":
        raise RuntimeError("Unexpected state: intermediate step must be PARTIAL")
    if stage=="validate":
        if result.get("status")!="SUCCESS" or result.get("functional_fails"):
            raise RuntimeError("Validation did not pass; Neon state is not advanced")
        complete_run(db_url,data["run_id"],"RUN1" if batch=="initial" else "RUN2",result,workspace)
    data["last_completed"]=stage
    STATE_PATH.parent.mkdir(exist_ok=True,parents=True)
    STATE_PATH.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
    receipt = {
      "classification":"SYNTHETIC_EDUCATIONAL_NOT_TIKTOK",
      "execution":"GITHUB_ACTIONS_REAL_PIPELINE_STAGE",
      "stage":stage,"batch":batch,"cycle":cycle,"run_id":data["run_id"],
      "result":result,
      "checkpoint":str(workspace/"lake"/"control"/f"checkpoint_{batch}.json"),
    }
    (workspace/"last_step_result.json").write_text(
        json.dumps(receipt,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    print(json.dumps({k:receipt[k] for k in ("execution","stage","batch","cycle","run_id")},
                     ensure_ascii=False))
    return receipt


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--stage",choices=STAGES,required=True)
    parser.add_argument("--batch",choices=("initial","incremental"),required=True)
    args=parser.parse_args()
    run_stage(args.stage,args.batch)


if __name__=="__main__":
    main()
