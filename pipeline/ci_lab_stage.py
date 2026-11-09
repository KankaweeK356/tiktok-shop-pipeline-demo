"""One *real* ETL stage per GitHub Actions run.

Previous workspace is restored from a GitHub Actions artifact by the workflow.
The same SQLite, Parquet, checkpoints and DuckDB files survive between jobs.
This cannot run against an already populated Neon cycle; explicit reset is required.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import pandas as pd
import duckdb
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



def _real_step_evidence(workspace: Path,batch: str,stage: str) -> dict:
    """Actual first five rows and measured record count, not fabricated examples."""
    def parquet_result(path):
        import pyarrow.parquet as pq
        if not path.is_file(): return {"records":0,"preview":[]}
        file=pq.ParquetFile(path)
        n=file.metadata.num_rows
        frame=next(file.iter_batches(batch_size=5)).to_pandas() if n else pd.DataFrame()
        return {"records":n,"preview":json.loads(frame.to_json(orient="records",date_format="iso"))}
    input_data={"label":"Actual source files","preview":[]}
    output={"origin":"GITHUB_WORKER_ACTUAL","preview":[]}
    if stage=="ingest":
        with sqlite3.connect(workspace/"er1.sqlite") as db:
            count=db.execute('SELECT COUNT(*) FROM "Fact_Orders"').fetchone()[0]
            cursor=db.execute('SELECT * FROM "Fact_Orders" LIMIT 5')
            cols=[x[0] for x in cursor.description]
            output={"table":"Fact_Orders","records":count,"origin":"NEW_NEON_INGEST",
                    "preview":[dict(zip(cols,row)) for row in cursor.fetchall()]}
    elif stage=="extract":
        output={**parquet_result(workspace/"lake"/"raw"/batch/"Fact_Orders.parquet"),
                "origin":"NEW_RAW_PARQUET_FROM_NEON"}
    elif stage=="transform":
        input_data=parquet_result(workspace/"lake"/"raw"/batch/"Fact_Order_Items.parquet")
        output={**parquet_result(workspace/"lake"/"standardized"/batch/"Fact_Sales_Order_Item.parquet"),
                "origin":"NEW_STANDARDIZED_DELTA"}
    elif stage=="load":
        input_data=parquet_result(workspace/"lake"/"standardized"/batch/"Fact_Sales_Order_Item.parquet")
        with duckdb.connect(str(workspace/"er2.duckdb"),read_only=True) as db:
            frame=db.execute('SELECT * FROM "Fact_Sales_Order_Item" LIMIT 5').df()
            count=db.execute('SELECT COUNT(*) FROM "Fact_Sales_Order_Item"').fetchone()[0]
        output={"table":"Fact_Sales_Order_Item","records":count,"origin":"NEW_DUCKDB_WAREHOUSE",
                "preview":json.loads(frame.to_json(orient="records",date_format="iso"))}
    else:
        report=json.loads((workspace/"reports"/("functional_"+batch+".json")).read_text())
        output={"table":"Validation","records":report.get("checks"),
                "origin":"NEW_FUNCTIONAL_VALIDATION",
                "preview":[{"check":"Checks","passed":report.get("passed"),"failed":report.get("failed")},
                    {"check":"Paid items","source":report.get("source_paid_item_count"),
                     "warehouse":report.get("warehouse_sales_item_count")},
                    {"check":"Net revenue","source":report.get("er1_net_revenue"),
                     "warehouse":report.get("er2_net_revenue")}]}
    return {"classification":"SYNTHETIC_EDUCATIONAL_NOT_TIKTOK",
        "mode":"REAL_GITHUB_ACTIONS_STAGE","is_new_etl_run":True,"stage":stage,"batch":batch,
        "executed_at":pd.Timestamp.utcnow().isoformat(),
        "success":True,"input":input_data,"output":output,
        "metrics":[{"label":"Output records","value":output.get("records",0)}],
        "checks":[{"label":"Actual orchestrator stage completed","pass":True}],
        "provenance":"NEW_WORKER_OUTPUT_NOT_HISTORICAL_REPLAY"}


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
    receipt["evidence"]=_real_step_evidence(workspace,batch,stage)
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
