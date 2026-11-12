"""Download, validate and apply a user-supplied monthly Source ZIP before Neon is touched."""
from __future__ import annotations
import csv, hashlib, json, os, urllib.error, urllib.request, zipfile
from pathlib import Path

from .er1 import SOURCE_ORDER
from .generate_classroom_source import BATCHES, BATCH_MONTHS
from .schema import ROOT, parse_dbml

API=os.environ.get("CLASSROOM_SOURCE_UPLOAD_API",
    "https://tiktok-shop-mlops-dashboard-git-feature-classroom-dea39b-newja.vercel.app/api/lab-batch")
MAX_ARCHIVE=4*1024*1024
MAX_EXPANDED=24*1024*1024

def _request(url: str, method="GET", data=None):
    request=urllib.request.Request(url,data=data,method=method,
        headers={"Content-Type":"application/json"} if data else {})
    try:
        with urllib.request.urlopen(request,timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"ส่งไฟล์ Source ไม่สำเร็จ (HTTP {error.code})") from None

def apply(upload_id: str, batch: str, source_root: Path, workspace: Path):
    if batch not in BATCHES:raise ValueError("Unknown monthly Source batch")
    batch_index=BATCHES.index(batch)
    expected_month=BATCH_MONTHS[batch_index].strftime("%Y-%m")
    archive=workspace/"source_upload.zip"
    archive.parent.mkdir(parents=True,exist_ok=True)
    # Keep the verified copy in the preserved Lab artifact so a retry does not
    # need the one-time upload token or an upload that was already consumed.
    if not archive.is_file():
        ticket=json.loads(_request(API+"?id="+upload_id))
        if ticket.get("month")!=expected_month:raise ValueError("Uploaded Source month does not match the next delivery")
        payload=_request(ticket["url"])
        if not payload or len(payload)>MAX_ARCHIVE:raise ValueError("Uploaded Source ZIP exceeds the allowed size")
        archive.write_bytes(payload)
        try:_request(API+"?id="+upload_id,"DELETE")
        except RuntimeError:pass
    if archive.stat().st_size>MAX_ARCHIVE:raise ValueError("Uploaded Source ZIP exceeds the allowed size")
    tables,_=parse_dbml(ROOT/"schemas"/"ER1_V3.dbml")
    columns={table.name:[column.name for column in table.columns] for table in tables}
    expected_names={table+".csv" for table in SOURCE_ORDER}|{"source_manifest.json"}
    with zipfile.ZipFile(archive) as package:
        infos=package.infolist()
        if len(infos)!=len(expected_names) or {item.filename for item in infos}!=expected_names:
            raise ValueError("ZIP must contain exactly the 21 ER1 Source tables and source_manifest.json")
        if sum(item.file_size for item in infos)>MAX_EXPANDED:
            raise ValueError("Uncompressed Source ZIP exceeds the allowed size")
        if any(item.file_size>MAX_EXPANDED or item.filename.startswith(("/","\\")) or ".." in Path(item.filename).parts for item in infos):
            raise ValueError("Unsafe or oversized file inside Source ZIP")
        manifest=json.loads(package.read("source_manifest.json"))
        if (manifest.get("month")!=expected_month or manifest.get("batch")!=batch or
            manifest.get("classification")!="SYNTHETIC_EDUCATIONAL_NOT_TIKTOK" or
            manifest.get("source_tables")!=SOURCE_ORDER):
            raise ValueError("Source ZIP month or ER1 table list does not match the next delivery")
        staging=workspace/"validated_source_upload"
        staging.mkdir(parents=True,exist_ok=True)
        for table in SOURCE_ORDER:
            name=table+".csv"
            data=package.read(name)
            with __import__("io").StringIO(data.decode("utf-8-sig"),newline="") as stream:
                header=next(csv.reader(stream),[])
            if header!=columns[table] or manifest.get("columns",{}).get(table)!=columns[table]:
                raise ValueError(f"{name} columns do not match ER1")
            (staging/name).write_bytes(data)
        (staging/"source_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False),encoding="utf-8")
    target=source_root/batch
    target.mkdir(parents=True,exist_ok=True)
    for table in SOURCE_ORDER:
        (target/(table+".csv")).write_bytes((staging/(table+".csv")).read_bytes())
    (target/"source_manifest.json").write_bytes((staging/"source_manifest.json").read_bytes())
    print(json.dumps({"source_upload":"VALIDATED","batch":batch,"month":expected_month,
        "tables":len(SOURCE_ORDER),"sha256":hashlib.sha256(archive.read_bytes()).hexdigest()}))

if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--upload-id",required=True)
    parser.add_argument("--batch",required=True,choices=BATCHES)
    args=parser.parse_args()
    apply(args.upload_id,args.batch,ROOT/"output"/"classroom_source",ROOT/"output"/"classroom_lab")
