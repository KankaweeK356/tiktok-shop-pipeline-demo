"""Run the complete real ETL batch inside a Vercel Python Function."""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import tempfile
import time
import urllib.request
import zipfile
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from uuid import UUID

import boto3
import psycopg

ROOT = Path(__file__).resolve().parents[1]
STAGES = ("ingest", "extract", "transform", "load", "validate")
INVOCATION_LOCK = threading.Lock()


class BlockedDQ(Exception):
    """The batch was stopped by the data-quality gate (not a system failure)."""

    def __init__(self, run_id: str, batch: str, issue_count: int, stage: str):
        self.run_id, self.batch, self.issue_count, self.stage = run_id, batch, issue_count, stage
        super().__init__("DQ_BLOCKED")
SOURCE_RELEASE = "https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/releases/download/classroom-source-v1/classroom-source-{month}.zip"


def storage():
    return boto3.client(
        "s3", endpoint_url=os.environ["CLASSROOM_STORAGE_ENDPOINT"],
        aws_access_key_id=os.environ["CLASSROOM_STORAGE_KEY_ID"],
        aws_secret_access_key=os.environ["CLASSROOM_STORAGE_SECRET"],
        region_name=os.environ.get("CLASSROOM_STORAGE_REGION", "auto"),
    )


def unpack_checked(data: bytes, root: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for item in archive.infolist():
            target = (root / item.filename).resolve()
            if root.resolve() not in target.parents and target != root.resolve():
                raise ValueError("Unsafe archive path")
        archive.extractall(root)


def read_ticket(ticket: str) -> dict:
    encoded, supplied = ticket.split(".", 1)
    secret = os.environ["CLASSROOM_LAB_ADMIN_KEY"].encode()
    expected = hmac.new(secret, encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        raise ValueError("RUN_TICKET_INVALID")
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    if int(payload.get("expires_at", 0)) < int(time.time() * 1000):
        raise ValueError("RUN_TICKET_EXPIRED")
    return payload


def source_bytes(batch: str, upload_id: str | None):
    """Return ``(zip_bytes, uri, origin)`` for the active, version-locked Source.

    The bytes are *not trusted* here; ``stage_source`` verifies SHA-256, manifest,
    table set and headers before anything is written.
    """
    from pipeline import source_lock

    if upload_id:
        key = f"classroom-source-uploads/{upload_id}.zip"
        item = storage().get_object(Bucket=os.environ["CLASSROOM_STORAGE_BUCKET"], Key=key)
        return item["Body"].read(), f"s3://{os.environ['CLASSROOM_STORAGE_BUCKET']}/{key}", "CUSTOM_UPLOAD"
    month_number = 1 if batch == "initial" else int(batch[-2:]) + 1
    month = f"2026-{month_number:02d}"
    version = source_lock.active_version()
    if version == source_lock.LEGACY_VERSION:
        url = SOURCE_RELEASE.format(month=month)
        request = urllib.request.Request(url, headers={"User-Agent": "classroom-vercel-runner"})
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.status != 200:
                raise RuntimeError("SOURCE_DOWNLOAD_FAILED")
            return response.read(), url, "GITHUB_RELEASE_V1"
    # Version-locked Source: location is configuration, identity is the approved SHA-256.
    name = source_lock.zip_name(month, source_lock.load_lock(version))
    local = os.environ.get("CLASSROOM_SOURCE_LOCAL_DIR")
    if local:
        path = Path(local) / name
        return path.read_bytes(), str(path), "LOCAL_DIRECTORY"
    prefix = os.environ.get("CLASSROOM_SOURCE_V2_S3_PREFIX")
    if prefix:
        key = f"{prefix.strip('/')}/{name}"
        item = storage().get_object(Bucket=os.environ["CLASSROOM_STORAGE_BUCKET"], Key=key)
        return item["Body"].read(), f"s3://{os.environ['CLASSROOM_STORAGE_BUCKET']}/{key}", "OBJECT_STORAGE"
    base = os.environ.get("CLASSROOM_SOURCE_V2_BASE_URL", "").rstrip("/")
    if base.startswith("https://"):
        url = f"{base}/{name}"
        request = urllib.request.Request(url, headers={"User-Agent": "classroom-vercel-runner"})
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.status != 200:
                raise RuntimeError("SOURCE_DOWNLOAD_FAILED")
            return response.read(), url, "VERSIONED_URL"
    raise ValueError("SOURCE_LOCATION_NOT_CONFIGURED")


def stage_source(data: bytes, root: Path, batch: str, *, uri: str = "", origin: str = "RELEASE") -> dict:
    """Verify (hash, manifest, tables, headers, month/batch) then unpack. No write on failure.

    Used by every execution mode (Run Next Step, Run All, revalidation) so they
    can never diverge in what they accept."""
    from pipeline import source_lock

    identity = source_lock.verify_source_zip(data, batch, uri=uri, origin=origin)
    source_lock.unpack_verified(data, root / batch)
    source_lock.write_identity(root, identity)
    return identity


def csv_reader(value: str):
    import csv
    return csv.reader(io.StringIO(value))


def prior_workspace(client, bucket: str, run_id: str, workspace: Path, prior_batch: str):
    item = client.get_object(
        Bucket=bucket, Key=f"vercel-lab/workspace/{run_id}.zip"
    )
    unpack_checked(item["Body"].read(), workspace)
    session_path = workspace / "lab_session.json"
    if not session_path.is_file():
        raise RuntimeError("PREVIOUS_WORKSPACE_MISSING")
    session = json.loads(session_path.read_text(encoding="utf-8"))
    if session.get("batch") != prior_batch or session.get("last_completed") != "validate":
        raise RuntimeError("PREVIOUS_BATCH_NOT_COMPLETE")


def restore_run_workspace(client, bucket: str, run_id: str, workspace: Path):
    item = client.get_object(
        Bucket=bucket, Key=f"vercel-lab/workspace/{run_id}.zip"
    )
    unpack_checked(item["Body"].read(), workspace)
    session_path = workspace / "lab_session.json"
    if not session_path.is_file():
        raise RuntimeError("RUN_WORKSPACE_MISSING")


def put_json(client, bucket: str, key: str, value: dict):
    client.put_object(
        Bucket=bucket, Key=key,
        Body=json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"),
        ContentType="application/json",
    )


def zip_workspace(root: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())
    return buffer.getvalue()


def run_ticket(ticket: str) -> dict:
    claim = read_ticket(ticket)
    batch = claim.get("batch")
    previous = claim.get("previous_run_id")
    cycle = claim.get("cycle")
    if batch != "initial" and (not isinstance(previous, str) or previous == "0"):
        raise ValueError("PREVIOUS_RUN_REQUIRED")
    UUID(claim.get("nonce"))
    os.environ["CLASSROOM_RUN_ID"] = claim["nonce"]
    os.environ["NEON_DEMO_DATABASE_URL"] = os.environ["CLASSROOM_LAB_WRITER_URL"]
    os.environ["CLASSROOM_EXECUTION_ENGINE"] = "VERCEL_NATIVE"
    os.environ["CLASSROOM_EXPECTED_CYCLE"] = str(int(cycle))
    bucket = os.environ["CLASSROOM_STORAGE_BUCKET"]
    client = storage()

    with tempfile.TemporaryDirectory(prefix="classroom-vercel-") as temp:
        root = Path(temp)
        workspace = root / "workspace"
        workspace.mkdir()
        source_root = root / "source"
        source_root.mkdir()
        os.environ["CLASSROOM_WORKSPACE"] = str(workspace)
        os.environ["CLASSROOM_SOURCE_ROOT"] = str(source_root)

        with psycopg.connect(os.environ["NEON_DEMO_DATABASE_URL"]) as db:
            state = db.execute(
                "SELECT phase,cycle_number,last_run_id FROM demo_control.dataset_state "
                "WHERE dataset_key='classroom'"
            ).fetchone()
            if not state or int(state[1]) != int(cycle):
                raise RuntimeError("LAB_CYCLE_CHANGED")
            expected_phase = "EMPTY" if batch == "initial" else (
                "RUN1_READY" if batch == "incremental_01" else "RUN2_READY"
            )
            if state[0] != expected_phase:
                raise RuntimeError("LAB_PHASE_CHANGED")
            if batch == "initial" and state[2] is not None:
                raise RuntimeError("INITIAL_RUN_ALREADY_EXISTS")
            if batch != "initial" and str(state[2] or "") != previous:
                raise RuntimeError("PREVIOUS_RUN_MISMATCH")
            # Never mix Source datasets inside one cycle (e.g. v1 'H2026..' IDs with Final 'ORD-..').
            from pipeline import source_lock, neon_control
            earlier = neon_control.previous_source_version(os.environ["NEON_DEMO_DATABASE_URL"], int(cycle))
            if earlier and earlier != source_lock.active_version():
                raise RuntimeError("LAB_SOURCE_VERSION_MIXED: cycle uses " + earlier +
                                   ", worker is configured for " + source_lock.active_version())

        target_stage = claim.get("stage")
        from pipeline.generate_classroom_source import BATCHES
        if target_stage and target_stage != "ingest":
            restore_run_workspace(client, bucket, claim["nonce"], workspace)
        else:
            if batch != "initial":
                prior_batch = BATCHES[BATCHES.index(batch) - 1]
                prior_workspace(client, bucket, previous, workspace, prior_batch)
        source_root.mkdir(exist_ok=True)
        data, uri, origin = source_bytes(batch, claim.get("source_upload_id"))
        identity = stage_source(data, source_root, batch, uri=uri, origin=origin)

        # Import after CLASSROOM_WORKSPACE is set so the real checkpoint files
        # live in this invocation's temporary directory, not the deployed bundle.
        from pipeline import ci_lab_stage, ci_lab_batch, ci_lab_export
        # Warm instances retain imported modules after /tmp has been removed.
        # Each invocation must bind all readers to its own restored workspace.
        for module in (ci_lab_stage, ci_lab_batch, ci_lab_export):
            module.STATE_PATH = workspace / "lab_session.json"
        from pipeline.ci_lab_batch import run_stage_and_save, finalize
        from pipeline.ci_lab_export import main as export_warehouse
        try:
            stages_to_run = [target_stage] if target_stage else STAGES
            for stage in stages_to_run:
                receipt = run_stage_and_save(batch, stage)
                put_json(client, bucket,
                         f"vercel-lab/results/{receipt['run_id']}/{stage}.json", receipt)
                client.put_object(
                    Bucket=bucket, Key=f"vercel-lab/workspace/{receipt['run_id']}.zip",
                    Body=zip_workspace(workspace), ContentType="application/zip",
                )
            if target_stage and target_stage != "validate":
                summary = {"batch": batch, "status": "PARTIAL", "run_id": receipt["run_id"],
                           "last_completed_stage": target_stage, "stage": target_stage}
                return {"run_id": receipt["run_id"], "batch": batch, "stage": target_stage, "summary": summary}
            summary = finalize(batch)
            export_warehouse()
        except Exception as error:
            session_path = workspace / "lab_session.json"
            if session_path.is_file():
                session = json.loads(session_path.read_text(encoding="utf-8"))
                run_id = session.get("run_id")
                # Only a session that belongs to THIS batch can describe this failure; a refusal
                # before begin_run still sees the previous month's session and must not touch it.
                if run_id and session.get("batch") == batch:
                    failed_stage = stage
                    error_code = type(error).__name__
                    history = workspace / "lake" / "control" / "stage_history.jsonl"
                    if history.is_file():
                        for line in reversed(history.read_text(encoding="utf-8").splitlines()):
                            try:
                                item = json.loads(line)
                                if item.get("batch") == batch and item.get("status") == "FAILED":
                                    failed_stage = item.get("stage")
                                    error_code = item.get("error_code") or error_code
                                    break
                            except Exception:
                                continue
                    dq_report = getattr(error, "report", None)
                    if dq_report is not None:
                        # run_stage already persisted BLOCKED_DQ + issues in Neon. Keep a
                        # durable, run-scoped copy of the evidence outside the temp workspace.
                        put_json(client, bucket, f"vercel-lab/blocked/{run_id}/dq_report.json", dq_report)
                        quarantine = workspace / "lake" / "governance" / "quarantine"
                        for item in sorted(quarantine.glob(f"{batch}_*")) if quarantine.is_dir() else []:
                            client.put_object(Bucket=bucket,
                                              Key=f"vercel-lab/blocked/{run_id}/{item.name}",
                                              Body=item.read_bytes(), ContentType="application/json")
                        put_json(client, bucket, f"vercel-lab/failed/{run_id}.json", {
                            "status": "BLOCKED_DQ", "failure_class": "DATA_QUALITY", "run_id": run_id,
                            "batch": batch, "cycle": cycle, "failed_stage": failed_stage,
                            "error_code": "DQ_BLOCKED", "issue_count": len(dq_report["issues"]),
                            "message": "ข้อมูลไม่ผ่านการตรวจคุณภาพ · หยุดก่อน Publish · ตรวจสอบและแก้ไขใน Review & Fix",
                        })
                        raise BlockedDQ(run_id, batch, len(dq_report["issues"]), failed_stage) from error
                    try:
                        from pipeline.neon_control import fail_run
                        fail_run(os.environ["NEON_DEMO_DATABASE_URL"], run_id,
                                 "RUN1" if batch == "initial" else "RUN2", workspace,
                                 RuntimeError("VERCEL_WORKER_FAILED"), batch=batch)
                    except Exception:
                        pass
                    put_json(client, bucket, f"vercel-lab/failed/{run_id}.json", {
                        "status": "FAILED", "run_id": run_id, "batch": batch,
                        "cycle": cycle, "failed_stage": failed_stage,
                        "error_code": str(error_code)[:100],
                        "message": "หยุดที่ขั้น " + str(failed_stage or "บันทึกผล") +
                                   " · รหัสสาเหตุ " + str(error_code)[:100] +
                                   " · ตรวจรายละเอียดในผลของขั้นตอน แล้วกดรันชุดเดิมอีกครั้งหลังแก้ข้อมูลหรือระบบพร้อม",
                    })
            raise

        run_id = str(summary["run_id"])
        try:
            summary["execution"] = "VERCEL_NATIVE"
            summary["source_month"] = f"2026-{BATCHES.index(batch) + 1:02d}"
            for stage in STAGES:
                path = workspace / "batch_results" / batch / f"{stage}.json"
                put_json(client, bucket, f"vercel-lab/results/{run_id}/{stage}.json",
                         json.loads(path.read_text(encoding="utf-8")))
            put_json(client, bucket, f"vercel-lab/results/{run_id}/batch.json", summary)
            warehouse = workspace / "warehouse_csv.zip"
            if not warehouse.is_file():
                raise RuntimeError("WAREHOUSE_EXPORT_MISSING")
            client.put_object(
                Bucket=bucket, Key=f"vercel-lab/results/{run_id}/warehouse.zip",
                Body=warehouse.read_bytes(), ContentType="application/zip",
            )
            client.put_object(
                Bucket=bucket, Key=f"vercel-lab/workspace/{run_id}.zip",
                Body=zip_workspace(workspace), ContentType="application/zip",
            )
            from pipeline.neon_control import complete_run
            validate_receipt = json.loads(
                (workspace / "batch_results" / batch / "validate.json").read_text(encoding="utf-8")
            )
            complete_run(os.environ["NEON_DEMO_DATABASE_URL"], run_id,
                         "RUN1" if batch == "initial" else "RUN2",
                         validate_receipt["result"], workspace,
                         artifact_uri=f"s3://{bucket}/vercel-lab/results/{run_id}/warehouse.zip")
            return {"run_id": run_id, "batch": batch, "summary": summary}
        except Exception as error:
            try:
                from pipeline.neon_control import fail_run
                fail_run(os.environ["NEON_DEMO_DATABASE_URL"], run_id,
                         "RUN1" if batch == "initial" else "RUN2", workspace,
                         RuntimeError("VERCEL_RESULT_PUBLISH_FAILED"), batch=batch)
            except Exception:
                pass
            put_json(client, bucket, f"vercel-lab/failed/{run_id}.json", {
                "status": "FAILED", "run_id": run_id, "batch": batch, "cycle": cycle,
                "failed_stage": "publish", "error_code": type(error).__name__,
                "message": "ขั้น ETL ผ่านแล้ว แต่บันทึกหลักฐานผลลัพธ์ไม่สำเร็จ · ลองรันชุดเดิมอีกครั้ง",
            })
            raise


def run_revalidation(ticket: str) -> dict:
    """Re-run the Stage 1 generic rules on raw rows + approved corrections.

    Writes only DQ control records (dq_revalidation) - never ER1/ER2 or the Source."""
    claim = read_ticket(ticket)
    batch, cycle, previous = claim.get("batch"), claim.get("cycle"), claim.get("previous_run_id")
    from pipeline.generate_classroom_source import BATCHES
    if batch not in BATCHES:
        raise ValueError("SOURCE_BATCH_INVALID")
    UUID(claim.get("nonce"))
    url = os.environ["CLASSROOM_LAB_WRITER_URL"]
    os.environ["NEON_DEMO_DATABASE_URL"] = url
    bucket = os.environ["CLASSROOM_STORAGE_BUCKET"]
    client = storage()
    with tempfile.TemporaryDirectory(prefix="classroom-reval-") as temp:
        root = Path(temp)
        workspace, source_root = root / "workspace", root / "source"
        workspace.mkdir()
        source_root.mkdir()
        with psycopg.connect(url) as db:
            state = db.execute("SELECT cycle_number FROM demo_control.dataset_state "
                               "WHERE dataset_key='classroom'").fetchone()
            if not state or int(state[0]) != int(cycle):
                raise RuntimeError("LAB_CYCLE_CHANGED")
            blocked = db.execute(
                "SELECT 1 FROM demo_control.pipeline_runs WHERE dataset_key='classroom' AND cycle_number=%s "
                "AND status IN ('BLOCKED_DQ','READY_TO_RESUME') AND result_summary->>'batch'=%s LIMIT 1",
                (int(cycle), batch)).fetchone()
            if not blocked:
                raise RuntimeError("LAB_NO_BLOCKED_RUN")
        if batch != "initial":
            prior_workspace(client, bucket, previous, workspace, BATCHES[BATCHES.index(batch) - 1])
        data, uri, origin = source_bytes(batch, claim.get("source_upload_id"))
        identity = stage_source(data, source_root, batch, uri=uri, origin=origin)
        from pipeline import dq_recovery, neon_control
        context = neon_control.load_correction_context(url, int(cycle), batch, identity["zip_sha256"])
        report = dq_recovery.revalidate(workspace, source_root / batch, batch, identity, context)
        outcome = neon_control.record_revalidation(
            url, int(cycle), batch, identity["zip_sha256"], report, context["correction_set_id"],
            str(claim.get("actor") or "")[:120] or None)
        put_json(client, bucket, f"vercel-lab/revalidation/{outcome['reval_id']}.json", report)
        return {"run_id": str(claim["nonce"]), "batch": batch, "stage": "revalidate",
                "status": outcome["status"], "summary": outcome}


class handler(BaseHTTPRequestHandler):
    def reply(self, status: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= 4096:
                return self.reply(400, {"error": "คำขอ Run ไม่ถูกต้อง"})
            request = json.loads(self.rfile.read(size))
            if not INVOCATION_LOCK.acquire(blocking=False):
                return self.reply(409, {"accepted": False, "error_code": "WORKER_BUSY",
                                        "error": "มีงานกำลังประมวลผล กรุณารอแล้วตรวจสถานะ"})
            try:
                ticket = str(request.get("ticket", ""))
                result = (run_revalidation(ticket) if read_ticket(ticket).get("action") == "revalidate"
                          else run_ticket(ticket))
            finally:
                INVOCATION_LOCK.release()
            self.reply(200, {"accepted": True, "status": result.get("status", "SUCCEEDED"),
                             "run_id": result["run_id"], "batch": result["batch"],
                             "stage": result.get("stage"), "summary": result.get("summary")})
        except BlockedDQ as blocked:
            self.reply(409, {"accepted": False, "status": "BLOCKED_DQ", "error_code": "DQ_BLOCKED",
                             "failure_class": "DATA_QUALITY", "run_id": blocked.run_id,
                             "batch": blocked.batch, "failed_stage": blocked.stage,
                             "issue_count": blocked.issue_count,
                             "error": "Pipeline หยุดที่ DQ Gate: พบข้อมูลไม่ผ่านการตรวจคุณภาพ"})
        except Exception as error:
            # Detailed safe error code comes from the pipeline's stage receipt;
            # never include environment values or stack traces in HTTP output.
            message = str(error)
            code = message.split(":", 1)[0] if message else type(error).__name__
            self.reply(409 if code.startswith(("LAB_", "PREVIOUS_", "INITIAL_")) else 500,
                       {"accepted": False, "status": "FAILED",
                        "error_code": code[:80], "error": "Pipeline หยุด: " + code[:80]})

    def log_message(self, _format, *_args):
        return
