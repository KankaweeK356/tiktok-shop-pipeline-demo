"""Publish small, sanitized, REAL lab step evidence for the static Vercel UI.

This is deliberately *not* the full runner workspace or a credential-bearing
artifact. Each record is sampled from actual Neon/Parquet/DuckDB executions.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

from .schema import ROOT

ALLOWED = {"ingest","extract","transform","load","validate"}
ALLOWED_BATCHES = {"initial","incremental"}


def main():
    source=ROOT/"output"/"classroom_lab"/"last_step_result.json"
    if not source.is_file():
        raise FileNotFoundError("Missing real Python step evidence")
    payload=json.loads(source.read_text(encoding="utf-8"))
    evidence=payload.get("evidence",{})
    if (payload.get("execution")!="GITHUB_ACTIONS_REAL_PIPELINE_STAGE" or
        evidence.get("mode")!="REAL_GITHUB_ACTIONS_STAGE" or
        evidence.get("classification")!="SYNTHETIC_EDUCATIONAL_NOT_TIKTOK"):
        raise RuntimeError("Refusing to publish unverified or mock step")
    batch=payload["batch"];stage=payload["stage"]
    if batch not in ALLOWED_BATCHES or stage not in ALLOWED:
        raise ValueError("Unexpected lab batch/stage")
    # Explicit fields only; no database URL, env vars, logs or arbitrary paths.
    public={
       "batch":batch,"stage":stage,
       "git_run_id":os.environ.get("GITHUB_RUN_ID",""),
       "source_engine":"NEON_POSTGRESQL_CLASSROOM_STEP_LAB",
       "source_type":"SYNTHETIC_EDUCATIONAL_NOT_TIKTOK",
       "cycle":payload["cycle"],
       "lab_run_id":payload["run_id"],
       "evidence":{key:evidence.get(key) for key in (
           "classification","mode","is_new_etl_run","stage","batch",
           "executed_at","success","input","output","metrics","checks","provenance"
       )}
    }
    destination=ROOT/"dashboard"/"data"/"lab_steps"
    destination.mkdir(parents=True,exist_ok=True)
    path=destination/f"{batch}_{stage}.json"
    path.write_text(json.dumps(public,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf-8")
    index=ROOT/"dashboard"/"data"/"lab_manifest.json"
    if index.is_file():
        manifest=json.loads(index.read_text(encoding="utf-8"))
    else:
        manifest={"schema_version":"real_lab_steps_v1","runs":[]}
    manifest["source"]="REAL_GITHUB_ACTIONS_SEPARATE_STAGES"
    manifest["data_classification"]="SYNTHETIC_EDUCATIONAL_NOT_TIKTOK"
    manifest["lab_branch"]="classroom-step-lab"
    entry={"batch":batch,"stage":stage,"run_id":public["git_run_id"],
           "executed_at":evidence["executed_at"],"file":"./data/lab_steps/"+path.name}
    manifest["runs"]=[r for r in manifest["runs"] if (r["batch"],r["stage"])!=(batch,stage)]
    manifest["runs"].append(entry)
    manifest["runs"].sort(key=lambda r:(r["batch"],ALLOWED_ORDER.index(r["stage"])))
    index.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Published a verified stage sample:",batch,stage,"run",public["git_run_id"])


ALLOWED_ORDER = ["ingest","extract","transform","load","validate"]
if __name__=="__main__":
    main()
