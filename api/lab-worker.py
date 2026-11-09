"""Complete one real batch on Vercel and keep its workspace for Run 2."""
import io, json, os, tempfile, zipfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from uuid import UUID
import boto3, psycopg

STAGES = ("ingest", "extract", "transform", "load", "validate")
def s3():
    return boto3.client("s3", endpoint_url=os.environ["CLASSROOM_STORAGE_ENDPOINT"],
        aws_access_key_id=os.environ["CLASSROOM_STORAGE_KEY_ID"],
        aws_secret_access_key=os.environ["CLASSROOM_STORAGE_SECRET"],
        region_name=os.environ.get("CLASSROOM_STORAGE_REGION", "auto"))
def pack(root):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob("*"):
            if path.is_file(): archive.write(path, path.relative_to(root).as_posix())
    return buffer.getvalue()
def unpack(data, root):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for item in archive.infolist():
            target = (root / item.filename).resolve()
            if root.resolve() not in target.parents and target != root.resolve():
                raise ValueError("Unsafe workspace archive")
        archive.extractall(root)
def lab_phase():
    with psycopg.connect(os.environ["CLASSROOM_LAB_WRITER_URL"]) as db:
        row = db.execute("SELECT phase,cycle_number FROM demo_control.dataset_state "
                         "WHERE dataset_key='classroom'").fetchone()
    if not row: raise RuntimeError("Lab state missing")
    return row
class handler(BaseHTTPRequestHandler):
    def reply(self, code, value):
        body = json.dumps(value, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_POST(self):
        secret = os.environ.get("CLASSROOM_LAB_ADMIN_KEY")
        if not secret or self.headers.get("X-Classroom-Worker-Key") != secret:
            return self.reply(403, {"error":"Forbidden"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 2 <= size <= 1024: return self.reply(400, {"error":"Invalid request"})
            request = json.loads(self.rfile.read(size))
            if request.get("check") is True:
                current, _cycle = lab_phase()
                s3().list_objects_v2(Bucket=os.environ["CLASSROOM_STORAGE_BUCKET"],
                                     Prefix="vercel-lab/", MaxKeys=1)
                return self.reply(200, {"ready":True,"phase":current})
            batch, previous = request.get("batch"), request.get("previous_run_id")
            if batch not in ("initial","incremental") or not isinstance(previous,str):
                return self.reply(400, {"error":"Invalid batch"})
            if (batch == "initial" and previous != "0") or (
                batch == "incremental" and not self.valid_uuid(previous)):
                return self.reply(400, {"error":"Invalid predecessor"})
            current, cycle = lab_phase()
            if current != ("EMPTY" if batch=="initial" else "RUN1_READY"):
                return self.reply(409, {"error":"Lab phase changed"})
            bucket, client = os.environ["CLASSROOM_STORAGE_BUCKET"], s3()
            os.environ["NEON_DEMO_DATABASE_URL"] = os.environ["CLASSROOM_LAB_WRITER_URL"]
            with tempfile.TemporaryDirectory(prefix="classroom-vercel-") as temp:
                workspace = Path(temp)/"workspace"
                workspace.mkdir()
                if batch=="incremental":
                    data = client.get_object(Bucket=bucket,
                        Key=f"vercel-lab/workspace/{previous}.zip")["Body"].read()
                    unpack(data, workspace)
                    session = json.loads((workspace/"lab_session.json").read_text())
                    if session.get("batch")!="initial" or session.get("last_completed")!="validate":
                        raise RuntimeError("Run 1 workspace incomplete")
                os.environ["CLASSROOM_WORKSPACE"] = str(workspace)
                from pipeline.ci_lab_batch import run_stage_and_save, finalize
                receipts = [run_stage_and_save(batch, step) for step in STAGES]
                result = finalize(batch)
                from pipeline.ci_lab_export import main as export_warehouse
                export_warehouse()
                run_id = receipts[0]["run_id"]
                for receipt in receipts:
                    client.put_object(Bucket=bucket,
                        Key=f"vercel-lab/results/{run_id}/{receipt['stage']}.json",
                        Body=json.dumps(receipt,default=str).encode(),
                        ContentType="application/json")
                client.put_object(Bucket=bucket,
                    Key=f"vercel-lab/results/{run_id}/batch.json",
                    Body=json.dumps(result,default=str).encode(),
                    ContentType="application/json")
                client.put_object(Bucket=bucket,
                    Key=f"vercel-lab/results/{run_id}/warehouse.zip",
                    Body=(workspace/"warehouse_csv.zip").read_bytes(),
                    ContentType="application/zip")
                client.put_object(Bucket=bucket,
                    Key=f"vercel-lab/workspace/{run_id}.zip",
                    Body=pack(workspace),ContentType="application/zip")
            self.reply(200, {"accepted":True,"run_id":run_id})
        except Exception as error:
            self.reply(500, {"error":type(error).__name__})
    @staticmethod
    def valid_uuid(value):
        try: return str(UUID(value))==value
        except ValueError: return False
