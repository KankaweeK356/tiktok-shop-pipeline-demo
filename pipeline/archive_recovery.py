"""Non-destructive one-time evidence recovery to private Neon Object Storage.

Historical Run1 Parquet files are no longer available after the old CI runner
ended. This job DOES NOT misrepresent newly rebuilt files as original artifacts.
It reconstructs the DuckDB analytic result offline, verifies business totals
against current Neon, and extracts a NEW real Raw snapshot from live Neon.

A 256-bit random upload token is kept only in this runner. Its SHA256 hash and
short-lived prefix are stored in the control database. Vercel signs S3 uploads
using its own branch-scoped storage credentials; no extra GitHub secrets needed.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg

from .schema import ROOT
from .orchestrator import reset, run_batch
from .demo_tests import signature
from .neon_source import extract_neon

ORIGINAL_GITHUB_RUN = "42487488684"
BUCKET = "classroom-demo-lake"
API = os.environ.get(
    "CLASSROOM_STORAGE_SIGNER_URL",
    "https://tiktok-shop-mlops-dashboard-git-feature-classroom-dea39b-newja.vercel.app/api/storage-presign",
)
MAX_OBJECT_BYTES = 20 * 1024 * 1024


def _api_call(token: str, key: str, operation: str, size: int = 0) -> dict:
    data = json.dumps({"token": token, "key": key, "operation": operation,
                       "bytes": size}).encode("utf-8")
    req = urllib.request.Request(API, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # Never print URLs, connection strings, tokens or signed responses.
        raise RuntimeError(
            f"Archive signing service HTTP {error.code}; verify access and upload session"
        ) from None


def _upload_once(path: Path, token: str, key: str) -> tuple[str, int]:
    data = path.read_bytes()
    if not data or len(data) > MAX_OBJECT_BYTES:
        raise ValueError(f"Unsupported archive object size: {path.name}")
    ticket = _api_call(token, key, "upload", len(data))
    request = urllib.request.Request(
        ticket["url"], data=data,
        headers={"Content-Type": "application/octet-stream"},
        method="PUT")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status not in (200, 201, 204):
                raise RuntimeError("Storage upload did not return success")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Storage upload failed: HTTP {error.code}") from None
    remote = _api_call(token, key, "head")
    if int(remote.get("bytes", -1)) != len(data):
        raise AssertionError(f"Archive byte count mismatch for {path.name}")
    digest = hashlib.sha256(data).hexdigest()
    return digest, len(data)


def _start_session(db, prefix: str) -> tuple[str, str]:
    token = secrets.token_hex(32)
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    with db.cursor() as cur:
        cur.execute(
            "SELECT phase,cycle_number,last_run_id FROM demo_control.dataset_state "
            "WHERE dataset_key='classroom' FOR UPDATE")
        phase, cycle, run_id = cur.fetchone()
        if phase != "RUN2_READY" or cycle != 1 or run_id is None:
            raise RuntimeError("Recovery requires verified cycle 1 RUN2_READY dataset")
        cur.execute(
            "SELECT status FROM demo_control.pipeline_runs WHERE run_id=%s",
            (run_id,))
        if cur.fetchone()[0] != "SUCCEEDED":
            raise RuntimeError("Historical run is not validated")
        cur.execute(
            """INSERT INTO demo_control.upload_sessions
               (run_id,token_sha256,allowed_prefix,max_object_bytes,expires_at)
               VALUES (%s,%s,%s,%s,now()+interval '45 minutes')""",
            (run_id, digest, prefix, MAX_OBJECT_BYTES))
    db.commit()
    return token, str(run_id)


def _source_total(db) -> tuple[int, int, str]:
    with db.cursor() as cur:
        cur.execute('SELECT count(*) FROM demo_er1."Fact_Orders"')
        orders = cur.fetchone()[0]
        cur.execute("""
           SELECT count(*),
                  COALESCE(round(sum(coalesce(i."Total_Selling_Amount",0)-
                        coalesce(i."Voucher_Allocated_Amount",0))::numeric,2),0)::text
             FROM demo_er1."Fact_Order_Items" i
             JOIN demo_er1."Fact_Orders" o ON o."Order_ID"=i."Order_ID"
            WHERE o."Current_Status" IN ('Paid','Shipped','Delivered')
        """)
        paid_items, revenue = cur.fetchone()
    return orders, paid_items, revenue


def main() -> None:
    db_url = os.environ.get("NEON_DEMO_DATABASE_URL")
    if not db_url:
        raise RuntimeError("NEON_DEMO_DATABASE_URL must be a protected GitHub Actions secret")
    workspace = ROOT / "output" / "recovered_cloud"
    with psycopg.connect(db_url) as db:
        if _source_total(db) != (900, 1147, "417092.85"):
            raise AssertionError("Live Neon no longer matches verified historical result")
        with db.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM demo_control.pipeline_artifacts "
                "WHERE artifact_uri LIKE %s",
                (f"neon-storage://{BUCKET}/recovery/cycle-1/github-{ORIGINAL_GITHUB_RUN}/%",))
            if cur.fetchone()[0]:
                print("Already archived; not overwriting prior verified recovery")
                return

    # Explicitly opt out of Neon writes while rebuilding the *local* warehouse.
    existing = os.environ.pop("NEON_DEMO_DATABASE_URL")
    try:
        reset(workspace)
        initial = run_batch(workspace, "initial")
        incremental = run_batch(workspace, "incremental")
        after = signature(workspace)
    finally:
        os.environ["NEON_DEMO_DATABASE_URL"] = existing
    if initial["functional_fails"] or incremental["functional_fails"]:
        raise AssertionError("Reconstructed local data failed validation")
    if after["orders"] != 1147 or round(float(after["sales"]),2) != 417092.85:
        raise AssertionError("Reconstructed DuckDB does not match historical source totals")

    # New live-source snapshot, not a re-creation of the old Run1 file.
    raw_result = extract_neon(ROOT / "source" / "incremental", db_url,
                              workspace / "lake", "source_current")
    raw_manifest = json.loads(
        (workspace/"lake"/"control"/"manifest_source_current.json").read_text())
    if (raw_manifest["raw"]["Fact_Orders"]["records"] != 900 or
        raw_manifest["raw"]["Fact_Order_Items"]["records"] != 1330 or
        raw_result["parquet_tables"] != 25):
        raise AssertionError("Neon Raw snapshot count mismatch")

    recovery = {
        "classification": "SYNTHETIC_EDUCATIONAL_NOT_TIKTOK",
        "recovery_kind": "NEW_NEON_SNAPSHOT_AND_OFFLINE_WAREHOUSE_RECONSTRUCTION",
        "original_github_run": ORIGINAL_GITHUB_RUN,
        "original_run1_parquet_available": False,
        "original_run2_parquet_available": False,
        "raw_source_current": "EXTRACTED_FROM_LIVE_NEON",
        "warehouse": "RECONSTRUCTED_OFFLINE_FROM_VERSIONED_SYNTHETIC_SOURCE",
        "live_neon_orders": 900,
        "live_neon_paid_items": 1147,
        "live_neon_net_revenue": "417092.85",
        "reconstructed_warehouse_paid_items": after["orders"],
        "reconstructed_warehouse_net_revenue": round(float(after["sales"]),2),
        "snapshot_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = workspace / "reports" / "cloud_recovery_manifest.json"
    manifest_path.parent.mkdir(parents=True,exist_ok=True)
    manifest_path.write_text(json.dumps(recovery,indent=2,ensure_ascii=False))

    files = []
    for group, stage, kind in [
        ("lake/raw/source_current","extract","LAKE_RAW"),
        ("lake/landing/source_current","extract","LAKE_LANDING"),
        ("lake/standardized/incremental","transform","LAKE_STANDARDIZED"),
        ("lake/control","extract","REPORT"),
        ("lake/governance","extract","REPORT"),
        ("reports","validate","REPORT")
    ]:
        root=workspace/group
        if not root.exists(): continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and (path.suffix in (".parquet",".json",".jsonl",".csv")):
                files.append((path,stage,kind))
    files.append((workspace/"er2.duckdb","load","WAREHOUSE"))
    if len([x for x in files if x[2]=="LAKE_RAW"])!=25:
        raise AssertionError("Live Neon Raw snapshot must contain all 25 tables")

    prefix=f"recovery/cycle-1/github-{ORIGINAL_GITHUB_RUN}/{uuid4().hex}/"
    with psycopg.connect(db_url) as db:
        token,run_id=_start_session(db,prefix)
        results=[]
        for index,(path,stage,kind) in enumerate(files,1):
            key=prefix+str(path.relative_to(workspace)).replace(os.sep,"/")
            digest, size=_upload_once(path,token,key)
            results.append((run_id,stage,kind,f"neon-storage://{BUCKET}/{key}",
                            digest,size))
            if index%10==0:
                print(f"Verified {index}/{len(files)} private objects")
        # Register metadata ONLY after all objects returned matching size.
        with db.cursor() as cur:
            cur.executemany(
                """INSERT INTO demo_control.pipeline_artifacts
                   (run_id,stage_name,artifact_type,artifact_uri,content_sha256,size_bytes)
                   VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (run_id,artifact_type,artifact_uri) DO NOTHING""",
                results)
            cur.execute("UPDATE demo_control.upload_sessions SET revoked=TRUE "
                        "WHERE token_sha256=%s",
                        (hashlib.sha256(token.encode("ascii")).hexdigest(),))
        db.commit()
    print(json.dumps({"status":"ARCHIVED","objects":len(results),
                      "live_raw_tables":25,"warehouse":"RECONSTRUCTED_VERIFIED",
                      "original_historical_parquet_restored":False},ensure_ascii=False))


if __name__ == "__main__":
    main()
