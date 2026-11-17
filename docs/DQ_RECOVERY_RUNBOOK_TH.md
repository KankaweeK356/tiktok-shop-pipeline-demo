# Runbook: Final Source, Generic DQ Gate และ Error Recovery

เอกสารนี้อธิบายสิ่งที่ **Implement แล้วใน Code** และขั้นตอนที่ **ต้องให้ Product Owner อนุมัติ/ทำเอง** ก่อนใช้บน Cloud จริง ไม่มีขั้นตอนใดในเอกสารนี้ถูกรันกับ Neon/S3/Vercel จริงโดย Dev

## 1. สิ่งที่เปลี่ยนในระบบ
| ส่วน | พฤติกรรม |
|---|---|
| Source | `pipeline/source_lock.py` ตรวจ SHA-256 ของ ZIP, Manifest ฝังใน ZIP (รวม SHA-256/จำนวนแถวต่อไฟล์), ชุดตาราง, Header, เดือน/Batch ก่อนเขียนข้อมูล บันทึก Source Identity ลง `pipeline_runs.result_summary` และ `pipeline_artifacts` |
| DQ Engine | `pipeline/dq.py` สร้างกฎจาก `ER1_V3.dbml` (21 REFERENCE_EXISTS, PK_UNIQUE, NOT_NULL = 92 กฎ) นับแถวที่ตรวจ/ไม่ผ่านจริง รายงานแยกจาก 18/21/24 Reconciliation Checks เดิม |
| Stage 1 | `er1.ingest`: CSV → Staging (หน่วยความจำ) → DQ → Promote ใน Transaction เดียว ไม่ผ่าน = ไม่มีอะไรเข้า ER1 |
| Stage 3 | `transform.transform`: ตรวจซ้ำ Reference/PK บน Raw Parquet ก่อนสร้าง Standardized |
| Control | `sql/neon_dq_recovery_migration.sql` (Additive): `dq_rule_result`, `dq_issue` (หลักฐานต้นฉบับแก้ไม่ได้), `dq_correction` (Append-only), `dq_revalidation`, `published_snapshot`, สถานะ `BLOCKED_DQ`/`READY_TO_RESUME`/`FAILED_SYSTEM` พร้อม Trigger ควบคุมการเปลี่ยนสถานะ |
| API | `/api/lab-batch-result?dq=state|candidates|history|rules` (GET) และ `dq=correct|revalidate` (POST) ใน `lib/lab-dq.js` ไม่เพิ่ม Vercel Function |
| Worker | `api/lab-worker.py`: ตอบ `409 BLOCKED_DQ`, เก็บหลักฐานที่ `vercel-lab/blocked/{run_id}/`, `run_revalidation`, ปฏิเสธ Resume ถ้ายังไม่ Revalidate ผ่าน |
| UI | `dashboard/app.js` แสดง Review & Fix จาก Neon (รอด Refresh) ลบข้อมูล Hardcode ของ March ออก; `dashboard/pipeline-state.js` ตัดสินสถานะเดือน/Stage จาก Run ที่ Backend ยืนยันเท่านั้น |

Business KPI FAIL (ยอดต่ำกว่าเป้า/กำไรต่ำกว่า 10%) ไม่หยุด Pipeline

## 2. ค่า Configuration (ไม่ได้เปลี่ยน Production)
| ตัวแปร | ความหมาย |
|---|---|
| `CLASSROOM_SOURCE_VERSION` | ว่าง/`classroom-source-v1` = Release เดิม (ค่าเริ่มต้น) · `classroom_v2_2026_11_16` = Final Source ล็อก Hash |
| `CLASSROOM_SOURCE_V2_S3_PREFIX` | Prefix ของ ZIP ใน Bucket เดิม เช่น `classroom-source-v2/` (แนะนำ: Object Storage แบบ Versioned/ล็อกการเขียนทับ) |
| `CLASSROOM_SOURCE_V2_BASE_URL` | ทางเลือก: URL HTTPS ที่ชี้ไปยังไฟล์ `classroom-source-2026-MM.zip` |
| `CLASSROOM_SOURCE_LOCAL_DIR` | เฉพาะ Dev/Test: โฟลเดอร์ ZIP ในเครื่อง |
ลำดับ: Custom Upload > Local Dir > S3 Prefix > Base URL ถ้าไม่ตั้งที่ใดเลย Worker หยุดด้วย `SOURCE_LOCATION_NOT_CONFIGURED`

## 3. ขั้นตอนที่ต้องขออนุมัติแยก (Dev ยังไม่ได้ทำ)
1. **เปิด Neon Test Branch** ใหม่จาก Branch Lab (ห้ามใช้ Cycle 33 เดิม) และตั้ง Writer URL ของ Branch ทดสอบให้ Deployment ทดสอบ
2. **Apply Migration** `sql/neon_dq_recovery_migration.sql` บน Test Branch (Idempotent; ทดสอบแล้วกับ PostgreSQL 16 สองรอบ) แล้วให้สิทธิ์ SELECT/INSERT/UPDATE ตารางใหม่แก่ Writer Role (ไม่ต้องมี DELETE/TRUNCATE)
3. **อัปโหลด 10 ZIP** ของ Final ไปยัง Object Storage ที่ตรวจ Hash ได้ (ห้ามเขียนทับ Release `classroom-source-v1`) และตั้ง `CLASSROOM_SOURCE_VERSION=classroom_v2_2026_11_16` + `CLASSROOM_SOURCE_V2_S3_PREFIX`
4. **Deploy** Preview (ต้องมี `vercel.json` ที่ Bundle `source_lock_classroom_v2.json` เข้า Worker) รัน Jan → Feb → Mar (คาดว่า BLOCKED_DQ) → Review & Fix → Revalidate → Resume → Apr–Oct
5. เมื่อผ่านบน Test Branch และ PO อนุมัติ จึงเริ่ม **Cycle ใหม่** บน Lab หลัก (Reset ต้องอนุมัติแยก) ห้ามรัน Final ต่อบน Cycle ที่เคยใช้ v1

Rollback: ถอด `CLASSROOM_SOURCE_VERSION` กลับเป็นค่าเดิม; ตารางใหม่ไม่กระทบตารางเดิมและ Drop ได้; Migration ไม่แตะ `demo_er1`

## 4. วิธีทดสอบในเครื่อง
```bash
# ทดสอบทั้งหมดที่ไม่ต้องใช้ฐานข้อมูล (ข้ามเองถ้าไม่มีแพ็กเกจ Final)
FINAL_SOURCE_PACKAGE=/path/TikTok_Shop_Mock_Data_FINAL_1_Error python -m pytest -q tests/
node --test tests/js/*.test.mjs

# End-to-end บน PostgreSQL ชั่วคราวในเครื่อง (ฐานข้อมูลต้องชื่อมีคำว่า test และเป็น local — ระบบจะลบ schema demo_control/demo_er1 ของฐานนั้น)
DQ_TEST_DATABASE_URL='postgresql://user@localhost/dq_test' FINAL_SOURCE_PACKAGE=... DQ_TEST_PG_PARENT=/path/with/node_modules/pg/package.json \
  python -m pytest -q tests/test_dq_recovery_postgres.py
```
Test ใช้ `qa_only/` และ `expected_kpi.csv` เป็นเฉลยอิสระเท่านั้น

## 5. ข้อจำกัดที่ทราบ
- ผู้ยืนยัน (Actor) ระบุเอง ระบบ Lab ไม่มีระบบผู้ใช้ จึงใช้ Same-Origin Check + Validation + Idempotency Key + Audit แทนการยืนยันตัวตน
- Run All ต่อเดือนถัดไปอัตโนมัติถูกควบคุมโดย Timer ของ Browser (แต่ละเดือนรันฝั่ง Server) ปิดหน้าเว็บ = หยุดต่อเดือนถัดไป สถานะอยู่ใน Neon กดรันต่อได้
- ข้อมูลตัวอย่าง/ตารางจำลองคงที่อื่นใน `dashboard/app.js` (เช่น รายการ Fallback ของ Source, Timeline แท็บ Process) เป็นของเดิม ไม่ได้ถูกแตะ นอกจากส่วนที่เป็นผล Stage/Run/DQ
