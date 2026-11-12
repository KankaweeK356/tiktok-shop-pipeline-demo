"""Run one selected, isolated Error Lab phase and publish structured evidence."""
from __future__ import annotations

import argparse
import json
import os
import uuid

import psycopg

from .demo_tests import error_suite
from .schema import ROOT


CASE_TEXT = {
    "N01": ("Database", "สินค้าอ้างถึงกลุ่มสินค้าที่ไม่มีในข้อมูลหลัก",
            "Neon ปฏิเสธ Product_Group_ID ที่ไม่มีอยู่ด้วย Foreign Key"),
    "E01": ("ingest", "รายการสั่งซื้ออ้างถึง SKU ที่ไม่มีอยู่",
            "ระบบตรวจพบ SKU ที่ไม่มีใน Dim_SKU"),
    "E02": ("ingest", "ไฟล์ออเดอร์ต้นทางหาย",
            "ระบบแจ้งไฟล์ Fact_Orders.csv ที่จำเป็นไม่พบ"),
    "T01": ("transform", "ข้อมูล Voucher ผิดกฎ",
            "ระบบตรวจพบข้อมูล Voucher ที่ไม่ผ่านกฎคุณภาพ"),
    "T02": ("transform", "ช่วงเวลา Campaign ซ้อนกัน",
            "ระบบตรวจพบช่วงเวลา Campaign ที่ทับซ้อนกัน"),
    "L01": ("load", "โหลด Warehouse ไม่สำเร็จ",
            "ระบบหยุดโหลดและรักษาข้อมูล Warehouse เดิมไว้"),
}


def neon_fk_recovery(url: str, phase: str) -> dict:
    probe_sku = "ERROR_TEST_" + uuid.uuid4().hex
    missing_group = "MISSING_GROUP_" + uuid.uuid4().hex
    with psycopg.connect(url) as db:
        try:
            with db.cursor() as cur:
                cur.execute('SELECT "Product_Group_ID" FROM demo_er1."Dim_Product_Group" LIMIT 1')
                known = cur.fetchone()
                if not known:
                    raise RuntimeError("Neon has no product group to verify a successful retry")
                cur.execute('SAVEPOINT before_bad_sku')
                try:
                    cur.execute('INSERT INTO demo_er1."Dim_SKU" '
                                '("SKU_ID","Product_Group_ID") VALUES (%s,%s)',
                                (probe_sku, missing_group))
                except psycopg.errors.ForeignKeyViolation:
                    cur.execute('ROLLBACK TO SAVEPOINT before_bad_sku')
                else:
                    raise RuntimeError("Neon failed to reject unknown product group")
                if phase == "fix":
                    cur.execute('INSERT INTO demo_er1."Dim_SKU" '
                                '("SKU_ID","Product_Group_ID") VALUES (%s,%s)',
                                (probe_sku, known[0]))
                    cur.execute('SELECT COUNT(*) FROM demo_er1."Dim_SKU" WHERE "SKU_ID"=%s',
                                (probe_sku,))
                    if cur.fetchone()[0] != 1:
                        raise RuntimeError("Valid SKU retry failed")
        finally:
            db.rollback()
    with psycopg.connect(url) as check:
        with check.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM demo_er1."Dim_SKU" WHERE "SKU_ID"=%s',
                        (probe_sku,))
            if cur.fetchone()[0] != 0:
                raise RuntimeError("Error test left a row in Neon")
    if phase == "fail":
        return {"stage": "Database", "error_code": "FOREIGN_KEY_VIOLATION",
                "error_message": "Product_Group_ID ที่อ้างถึงไม่มีใน Dim_Product_Group; Neon ปฏิเสธการบันทึก",
                "title": CASE_TEXT["N01"][1], "fix": "เลือก Product_Group_ID ที่มีอยู่จริง แล้วตรวจความสัมพันธ์ก่อนบันทึก",
                "source_rows": [{"SKU_ID": probe_sku, "Product_Group_ID": missing_group}],
                "rollback": "ย้อนรายการทดสอบแล้ว ไม่เหลือข้อมูลใน Neon"}
    return {"retry_status": "PASS",
            "before": {"ผลตรวจ": "Neon ปฏิเสธ Product_Group_ID ที่ไม่มีจริง"},
            "after": {"ผลตรวจ": "ทดลองซ้ำด้วยกลุ่มที่มีจริงผ่าน และย้อนรายการทดสอบแล้ว"},
            "result_rows": [], "rollback": "ไม่มีข้อมูลทดสอบค้างใน Neon"}


def run_local_case(case: str, phase: str) -> dict:
    stop = phase == "fail"
    cases = error_suite(ROOT / "output" / "classroom_error", cases=[case],
                        stop_after_detection=stop)
    if cases.empty:
        raise RuntimeError("Selected Error Lab case produced no result")
    row = cases.iloc[0].to_dict()
    if not bool(row.get("passed")):
        raise RuntimeError("Selected Error Lab case did not pass its " + phase + " check")
    if phase == "fail":
        stage, title, description = CASE_TEXT[case]
        return {"stage": stage, "title": title,
                "error_code": str(row.get("detected") or "ERROR_DETECTED"),
                "error_message": description + " · รหัส: " + str(row.get("detected") or "ERROR_DETECTED"),
                "fix": "ตรวจและแก้ข้อมูลตามกฎที่ระบุ จากนั้นกดปุ่ม “ให้ระบบแก้ตามแนวทาง แล้วรันต่อ” เพื่อให้ระบบตรวจซ้ำ",
                "source_rows": [], "source_file": None}
    return {"retry_status": "PASS",
            "before": {"สถานะ": str(row.get("before") or "พบปัญหา")},
            "after": {"สถานะ": str(row.get("after") or "ผ่านหลังแก้"),
                      "เริ่มตรวจซ้ำจาก": str(row.get("retry_from") or row.get("stage") or "ขั้นที่พบปัญหา")},
            "result_rows": []}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True, choices=sorted(CASE_TEXT))
    parser.add_argument("--phase", required=True, choices=("fail", "fix"))
    args = parser.parse_args()
    url = os.environ.pop("NEON_DEMO_DATABASE_URL", "")
    if not url:
        raise RuntimeError("Neon Lab credential missing")
    evidence = (neon_fk_recovery(url, args.phase) if args.case == "N01"
                else run_local_case(args.case, args.phase))
    output = {"status": "SUCCESS", "mode": "REAL_ISOLATED_ERROR_TEST",
              "case": args.case, "phase": args.phase}
    output["detected" if args.phase == "fail" else "recovery"] = evidence
    path = ROOT / "output" / "classroom_error_result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"case": args.case, "phase": args.phase, "status": "SUCCESS"}))


if __name__ == "__main__":
    main()
