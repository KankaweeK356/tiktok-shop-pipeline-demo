"""Two-click Error Lab: detect the failure, then correct and resume."""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
from pathlib import Path

import duckdb
import psycopg

from .generate import generate
from .orchestrator import run_batch
from .schema import ROOT

CASES = {
    "N01": ("สินค้าอ้างถึงกลุ่มที่ไม่มีอยู่", "Database", "FOREIGN_KEY_VIOLATION",
            "เปลี่ยน Product_Group_ID จาก MISSING_GROUP เป็น ERROR_DEMO_GROUP"),
    "E01": ("รายการสั่งซื้ออ้างถึง SKU ที่ไม่มีอยู่", "Source → Database", "ingest",
            "แก้ SKU_ID ใน Source ให้ตรงกับสินค้าอ้างอิง"),
    "E02": ("ไฟล์ออเดอร์ต้นทางหาย", "Source → Database", "ingest",
            "คืนไฟล์ Fact_Orders.csv ให้ครบ"),
    "T01": ("ข้อมูล Voucher ผิดกฎ", "Data Lake → Standardized", "transform",
            "แก้เงื่อนไข Voucher แล้วแปลงซ้ำ"),
    "T02": ("ช่วงเวลา Campaign ซ้อนกัน", "Data Lake → Standardized", "transform",
            "แก้ช่วงเวลา Campaign แล้วแปลงซ้ำ"),
    "L01": ("โหลด Warehouse ไม่สำเร็จ", "Data Lake → Warehouse", "load",
            "แก้ข้อมูลที่โหลด แล้วทำ Load ซ้ำ"),
}
AREA = ROOT / "output" / "classroom_error_work"
RESULT = ROOT / "output" / "classroom_error_result.json"

def write_result(value: dict) -> None:
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str),
                      encoding="utf-8")
    print(json.dumps({"case": value["case"], "phase": value["phase"],
                      "status": value["status"]}))

def neon_failure(url: str) -> dict:
    with (ROOT / "source" / "error_lab" / "N01.csv").open(
            newline="", encoding="utf-8") as file:
        row = next(csv.DictReader(file))
    with psycopg.connect(url) as db:
        with db.cursor() as cur:
            cur.execute('DELETE FROM demo_er1."Dim_SKU" WHERE "SKU_ID"=%s',
                        (row["SKU_ID"],))
            cur.execute('SELECT 1 FROM demo_er1."Dim_Product_Group" '
                        'WHERE "Product_Group_ID"=%s', ("ERROR_DEMO_GROUP",))
            if not cur.fetchone():
                raise RuntimeError("Error Lab reference row missing")
            cur.execute("SAVEPOINT before_bad_source")
            detected = False
            try:
                cur.execute('INSERT INTO demo_er1."Dim_SKU" '
                            '("SKU_ID","Product_Group_ID","SKU_Name") VALUES (%s,%s,%s)',
                            (row["SKU_ID"],row["Product_Group_ID"],row["SKU_Name"]))
            except psycopg.errors.ForeignKeyViolation:
                detected = True
                cur.execute("ROLLBACK TO SAVEPOINT before_bad_source")
            if not detected:
                raise RuntimeError("Neon did not reject invalid foreign key")
            cur.execute('SELECT COUNT(*) FROM demo_er1."Dim_SKU" WHERE "SKU_ID"=%s',
                        (row["SKU_ID"],))
            if cur.fetchone()[0]:
                raise RuntimeError("Failed row remained in Neon")
    return {"source_rows":[row],"error_code":"FOREIGN_KEY_VIOLATION",
            "error_message":"MISSING_GROUP ไม่มีในตาราง Dim_Product_Group",
            "failed_row_saved":False,
            "neon_table":"demo_er1.Dim_SKU","neon_row_count":0}

def neon_fix(url: str) -> dict:
    with (ROOT / "source" / "error_lab" / "N01.csv").open(
            newline="", encoding="utf-8") as file:
        original = next(csv.DictReader(file))
    corrected = {**original,"Product_Group_ID":"ERROR_DEMO_GROUP"}
    with psycopg.connect(url) as db:
        with db.cursor() as cur:
            cur.execute('INSERT INTO demo_er1."Dim_SKU" '
                        '("SKU_ID","Product_Group_ID","SKU_Name") VALUES (%s,%s,%s) '
                        'ON CONFLICT ("SKU_ID") DO UPDATE SET '
                        '"Product_Group_ID"=EXCLUDED."Product_Group_ID",'
                        '"SKU_Name"=EXCLUDED."SKU_Name"',
                        (corrected["SKU_ID"],corrected["Product_Group_ID"],
                         corrected["SKU_Name"]))
    with psycopg.connect(url) as db:
        actual = db.execute('SELECT "SKU_ID","Product_Group_ID","SKU_Name" '
                            'FROM demo_er1."Dim_SKU" WHERE "SKU_ID"=%s',
                            (corrected["SKU_ID"],)).fetchone()
    if not actual or actual[1]!="ERROR_DEMO_GROUP":
        raise RuntimeError("Corrected row was not saved")
    return {"before":original,"after":corrected,"retry_status":"PASS",
            "result_rows":[dict(zip(corrected.keys(),actual))],
            "neon_table":"demo_er1.Dim_SKU"}

def local_failure(case: str) -> dict:
    if AREA.exists():
        shutil.rmtree(AREA)
    source, workspace = AREA/"source", AREA/"workspace"
    AREA.mkdir(parents=True)
    generate(source,n_initial=80,n_incremental=12,seed=7400)
    bad_row = None
    if case=="E01":
        file=source/"initial"/"Fact_Order_Items.csv"
        with file.open(newline="",encoding="utf-8") as stream:
            rows=list(csv.DictReader(stream))
            columns=list(rows[0])
        rows[0]["SKU_ID"]="SKU_DOES_NOT_EXIST"
        bad_row=rows[0].copy()
        with file.open("w",newline="",encoding="utf-8") as stream:
            writer=csv.DictWriter(stream,fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    elif case=="E02":
        (source/"initial"/"Fact_Orders.csv").unlink()
    error=None
    try:
        run_batch(workspace,"initial",source,
                  inject_error=case if case in ("T01","T02","L01") else None)
    except Exception as caught:
        error=caught
    report=workspace/"reports"/"error_initial.json"
    evidence=json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
    if not error or evidence.get("stage")!=CASES[case][2]:
        raise RuntimeError("Expected error was not detected at the correct stage")
    (AREA/"session.json").write_text(json.dumps({"case":case,
        "failed_stage":evidence["stage"],"error_code":evidence.get("error_code"),
        "completed_before_failure":evidence.get("completed_before_failure",[])}),
        encoding="utf-8")
    return {"source_rows":[bad_row] if bad_row else [],
            "source_file":"Fact_Orders.csv (ไม่มีไฟล์)" if case=="E02" else None,
            "error_code":evidence.get("error_code",type(error).__name__),
            "error_message":str(error)[:240],
            "failed_stage":evidence["stage"],
            "completed_before_failure":evidence.get("completed_before_failure",[]),
            "failed_row_saved":False}

def local_fix(case: str) -> dict:
    session=json.loads((AREA/"session.json").read_text(encoding="utf-8"))
    if session["case"]!=case:
        raise RuntimeError("Previous failure does not match selected case")
    source,workspace=AREA/"source",AREA/"workspace"
    if case in ("E01","E02"):
        clean=AREA/"clean_source"
        generate(clean,n_initial=80,n_incremental=12,seed=7400)
        filename="Fact_Order_Items.csv" if case=="E01" else "Fact_Orders.csv"
        shutil.copy2(clean/"initial"/filename,source/"initial"/filename)
    result=run_batch(workspace,"initial",source,inject_error=None)
    if result["status"]!="SUCCESS" or result["functional_fails"]:
        raise RuntimeError("Corrected retry did not pass validation")
    checkpoint=json.loads((workspace/"lake"/"control"/"checkpoint_initial.json")
                          .read_text(encoding="utf-8"))
    resumed=next((step for step in ("ingest","extract","transform","load","validate")
                  if step not in session.get("completed_before_failure",[])),None)
    if resumed and resumed!=session["failed_stage"]:
        raise RuntimeError("Retry did not resume from failed stage")
    with duckdb.connect(str(workspace/"er2.duckdb"),read_only=True) as db:
        count=db.execute('SELECT COUNT(*) FROM "Fact_Sales_Order_Item"').fetchone()[0]
        preview=db.execute('SELECT * FROM "Fact_Sales_Order_Item" LIMIT 3').df()
    return {"retry_status":"PASS","retry_from":session["failed_stage"],
            "completed_stages":checkpoint["completed"],
            "result_rows":json.loads(preview.to_json(orient="records",date_format="iso")),
            "warehouse_rows":count}

def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--case",choices=CASES,required=True)
    parser.add_argument("--phase",choices=("fail","fix"),required=True)
    args=parser.parse_args()
    url=os.environ.pop("NEON_DEMO_DATABASE_URL","")
    if not url:
        raise RuntimeError("Error Lab credential missing")
    title,stage,_expected,fix=CASES[args.case]
    if args.phase=="fail":
        detail=neon_failure(url) if args.case=="N01" else local_failure(args.case)
        status="EXPECTED_ERROR"
    else:
        detail=neon_fix(url) if args.case=="N01" else local_fix(args.case)
        status="SUCCESS"
    write_result({"status":status,"mode":"REAL_ISOLATED_ERROR_TEST",
                  "case":args.case,"phase":args.phase,"title":title,
                  "stage":stage,"fix":fix,"detail":detail,
                  "branch":"classroom-error-lab"})

if __name__=="__main__":
    main()
