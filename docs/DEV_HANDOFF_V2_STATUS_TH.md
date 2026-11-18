# Dev Handoff v2 — สถานะการพัฒนา, Gap Audit และ Acceptance

> หลักฐานทั้งหมดในเอกสารนี้ได้จาก **ฐานข้อมูล PostgreSQL 16 ชั่วคราวในเครื่อง + Worker จริง + Source ZIP จริง (hash ตรง Manifest)**
> **ไม่ได้รันบน Neon / Vercel / S3 จริง** (ไม่มีสิทธิ์เข้าถึงใน Session นี้ และ Host Vercel ถูก Proxy ปฏิเสธ) การ Migration, Deploy และ Reset ยังไม่ได้ทำและต้องขออนุมัติ

## P0 — Gap Audit (EXISTS / BROKEN / MISSING)
| รายการ | สถานะก่อนแก้ | หลักฐาน | หลังแก้ |
|---|---|---|---|
| SHA ที่ Vercel Deploy จริง | **ตรวจไม่ได้ (BLOCKED)** | PR #7 head = `b476ea0`; เข้า `*.vercel.app` ไม่ได้ (proxy 403); มีเพียง check "Vercel Preview Comments" | ต้องให้ Owner ส่ง SHA/URL/Env จาก Vercel Dashboard |
| Source ที่ Runtime ใช้ | BROKEN | Worker ผูก Release `classroom-source-v1` (ชุดเก่า ไม่มี Error) | Source Lock SHA-256 ครบ 10 ZIP (`classroom_v2_2026_11_16`) ตรงกับ `SOURCE_PACKAGE_MANIFEST.json` และ `verify_delivery.py` ผ่าน |
| March Error ตรวจพบ | BROKEN | ไม่มี DQ Rule; Review & Fix เป็น UI จำลอง (`lab-worker.py` ไม่อ่าน `override`) | Generic DQ Gate + Review & Fix จริง (commit `712016b`) |
| `lib/etl-engine.js` fixture | BROKEN | ผลสมมติ + March fail ฮาร์ดโค้ด ไม่มีผู้เรียก | ลบแล้ว |
| `pollRunAllProgress` ส่ง `since` เป็นตัวเลข | **BROKEN (ยืนยันจากโค้ด)** | API ใช้ `Date.parse(since)` → NaN → 400 ตลอด | Client ส่ง ISO; API รับทั้ง epoch/ISO |
| Run All ต่อเดือนด้วย Browser Timer ข้าม May | BROKEN | `setTimeout(startRunAll)` ไม่มี Gate | แทนด้วย "Run This Month" และ "Run to May" (หยุดที่ พ.ค.) · Gate มิ.ย.–ต.ค. อยู่ที่ Server (API + Worker) |
| `marchBlocked` ใน `sessionStorage`/Memory | BROKEN | `app.js` | สถานะ DQ อ่านจาก Neon, รอด Refresh |
| สถานะเดือนใน Month Strip | PARTIAL | คำนวณฝั่ง Browser | Backend ส่ง `PUBLISHED/RUNNABLE/RUNNING/DATA_QUALITY_BLOCKED/SYSTEM_FAILED/LOCKED` + เหตุผล |
| Marketing GAP / 3 เกณฑ์ | MISSING | ER2 View ไม่มี GAP | คำนวณจาก Mart ที่ Publish แล้วใน `finalize` (ไม่แก้ ER2) |
| `demo_ml` 3 ตาราง | MISSING | ไม่มีในฐานข้อมูล | `sql/neon_demo_ml_migration.sql` (สำเนา v4 ไม่แก้ DDL) **ยังไม่ Apply** |
| Forecast รายเดือนถัดไป / Seal / Evaluation | MISSING | ML เดิมเป็น next-week + `report.json` คงที่ | `pipeline/monthly_forecast.py`, `lib/lab-forecast.js`, UI 2 หน้า |
| Scenario / Selected Plan | MISSING | — | `lib/scenario-calc.js` + `seal_plan` (Append-only, Server คำนวณซ้ำ) |
| UI 4 หน้าจอ | PARTIAL | Business/Pipeline/ML (weekly) | Business + KPI Gates, Pipeline (Month strip), Forecast & Planning, Forecast vs Actual |

## สิ่งที่ Implement (ไฟล์หลัก)
- **Pipeline / Control:** `pipeline/source_lock.py`, `dq.py`, `dq_recovery.py`, `neon_control.py`, `business_gates.py`, `monthly_forecast.py`, `ci_lab_batch.py`
- **API (ไม่เพิ่ม Function; ใช้ `?dq=` / `?fc=` ใน `api/lab-batch-result.js`):** `lib/lab-dq.js`, `lib/lab-forecast.js`, `lib/scenario-calc.js`, `api/lab-batch.js` (Gate + `months`), `api/lab-worker.py` (revalidate / forecast / Gate)
- **UI:** `dashboard/app.js`, `dashboard/pipeline-state.js`, `dashboard/index.html`
- **DB (ยังไม่ Apply):** `sql/neon_dq_recovery_migration.sql`, `sql/neon_demo_ml_migration.sql`
- **ข้อมูลวางแผน:** `pipeline/assets/planning_target_seed_v1.csv` + `dashboard/data/planning_targets_v1.json` (sha256 `51b25726…08f6`, ป้าย `SIMULATED_PRECONFIGURED_FOR_CLASSROOM`)
- **Test:** ดู `tests/test_dq_*.py`, `tests/test_monthly_forecast.py`, `tests/js/*.test.mjs`

## ผล ML จริง (จาก Rolling Run, ข้อมูล Final)
| เดือนเป้าหมาย | วิธี Official | เหตุผลที่ระบบบันทึก |
|---|---|---|
| มิ.ย. | BASELINE trailing_3_month_mean | INSUFFICIENT_VALIDATION: Walk-forward ได้เพียง 2 Origin (ต้อง ≥3) |
| ก.ค. | BASELINE | ML Shop WAPE 13.97% ไม่ชนะ Baseline 9.89% บน 3 Origin เดียวกัน |
| ส.ค. | BASELINE | ML 11.28% vs 8.03% (4 Origin) |
| ก.ย. | BASELINE | ML 11.58% vs 9.48% (5 Origin) |
| ต.ค. | BASELINE | ML 13.13% vs 10.04% (6 Origin) |
ML (Ridge รวมทุกกลุ่ม) ถูก Train/ประเมินจริงแต่ **ไม่ชนะ Baseline** บนข้อมูลสังเคราะห์ชุดนี้ ระบบจึงใช้ BASELINE และแสดงตามจริง ไม่อ้างว่าเป็น ML

## Acceptance Checklist (A01–A28)
สถานะ: PASS = ผ่านในเครื่อง (Local PG + Worker จริง) · PARTIAL · BLOCKED · NOT_TESTED. ไม่มีข้อใด PASS บน Cloud จริง

| ID | สถานะ | หลักฐาน / หมายเหตุ |
|---|---|---|
| A01 SHA/Cycle/Hash | **BLOCKED** (ส่วน Hash ZIP: PASS) | ZIP ทั้ง 10 ตรง Manifest (`test_01`, `verify_delivery.py`); SHA ที่ Deploy/Neon Cycle ตรวจไม่ได้ |
| A02 Jan Run This Month | PASS | `test_03`, UI Run |
| A03 Run Next Step ทีละ 1 Stage | NOT_TESTED | โค้ดเดิม (Worker รัน `stage` เดียว) ไม่ได้ทดสอบรอบนี้ |
| A04 Feb | PASS | `test_03` ไม่มีข้อมูลซ้ำ |
| A05 March Invalid SKU | PASS | `test_04`: `BLOCKED_DQ`, ER1 ไม่เปลี่ยน |
| A06 Refresh/2 Tabs | PARTIAL | Refresh ผ่านบน Browser; 2 Tabs ไม่ได้ทดสอบ |
| A07 แก้ด้วยคน → Revalidate → Publish | PASS | UI ครบวงจร (ภาพ 01–03) + `test_06–09` |
| A08 Run to May | PASS | UI: หยุดที่ พ.ค., มิ.ย. LOCKED |
| A09 May KPI | PASS | Net 83,821.69 / เป้า 91,000 / Profit 1,875.28 (เฉลย 1,875.33; ต่าง 0.05 จากการปัดเศษสูตรเดิม) / Protection 2.05% / Business FAIL, Pipeline PASS |
| A10 Marketing GAP 5 ส่วน | PASS | `test_11` เทียบเฉลยอิสระ (May GAP 45.26% FAIL) |
| A11 เป้า มิ.ย. ก่อน Source | PASS | 94,000 จาก Seed ที่ติดป้าย Simulated |
| A12 Forecast มิ.ย. | PASS | ใช้ข้อมูล ≤ พ.ค., 5 กลุ่ม, BASELINE พร้อมเหตุผล |
| A13 Seal | PASS | Official ครั้งเดียว, DB Trigger กันแก้, รอด Refresh |
| A14 Run มิ.ย. ก่อน Seal | PASS | Worker `LAB_FORECAST_NOT_SEALED`; API 409; UI ปุ่มปิดพร้อมเหตุผล |
| A15 Scenario + Plan | PASS | SC-01..04 (`scenario-calc.test.mjs`), `test_14` (v1/v2, Server คำนวณซ้ำ) |
| A16 Run มิ.ย. หลัง Seal | PASS | UI |
| A17 Forecast vs Actual | PASS | ใช้ Forecast ID เดิม; เทียบเฉลยรายกลุ่ม |
| A18 Forecast ก.ค. | PASS | `published_through=2026-06` |
| A19 ก.ค.–ต.ค. | PASS | 5 การเปรียบเทียบ (มิ.ย.–ต.ค.), Seal ก่อน Ingest ทุกเดือน |
| A20 ประเมินโมเดล | PASS | Rolling-origin + ผลข้างบน ไม่มีตัวเลขคงที่ |
| A21 Refresh/ตัดเน็ต/2 Tabs | PARTIAL | สถานะอยู่ใน Neon; **Run to May ควบคุมด้วย Browser Timer** (ไม่ Durable); ไม่ได้ทดสอบ 2 Tabs/ตัดเน็ต |
| A22 INCOMPLETE/MISSING_TARGET | PASS | Unit Tests (ไม่ใช้ 0/PASS) |
| A23 Invalid SKU อื่น + March สะอาด | PASS | `test_dq_gate.py` |
| A24 Publish Atomic | PARTIAL | Publish ใน Transaction เดียวกับ `complete_run`; ไม่ได้ทดสอบ Crash กลาง Stage 5 |
| A25 Voucher/Ads/GAP | PASS | Voucher ระดับคำสั่งซื้อ (Unit), GAP เทียบเฉลย |
| A26 Theme/Responsive | PARTIAL | ภาพ Desktop/Mobile อยู่ในโฟลเดอร์ handover; ไม่ได้เทียบ Pixel กับ Mockup |
| A27 QA Leak | PASS | Test ตรวจว่า Runtime ไม่อ้าง `qa_only`/`expected_kpi`/`golden` |
| A28 Migration/Rollback | PARTIAL | ทดสอบบน PG16 ในเครื่องสองไฟล์ (Idempotent); ยังไม่ Apply บน Neon |

## ข้อจำกัดที่ยังเหลือ (ตรงไปตรงมา)
1. Run to May ไม่ Durable (Browser Timer); ปุ่ม "Run Remaining Months" ไม่ได้ทำ (ตามเงื่อนไข: ต้อง Orchestrator ที่ตรวจ Gate ได้จริง)
2. Business Actual ยังใช้โค้ดเดิม (ผสม `report.json` คงที่ในบางส่วน) โดยเพิ่มแผง KPI Gates ที่อ่านจาก Published ER2; ยังไม่ได้ตัดข้อมูล Fallback เดิมทั้งหมด
3. ผู้ดำเนินการ (actor) ผู้ใช้กรอกเอง ไม่มีระบบ Authentication
4. หน้า ML Lab เดิม (weekly) ถอดออกจากเมนูแต่ยังไม่ลบโค้ด
5. ไม่ได้ทดสอบ Latency/Performance ของ Serverless ที่จริง

## ที่ต้องขออนุมัติ
1. สร้าง Neon Test Branch และ Apply สอง Migration (DQ + `demo_ml`), ให้สิทธิ์ Writer Role
2. อัปโหลด ZIP 10 เดือนไป Object Storage + ตั้ง `CLASSROOM_SOURCE_*`
3. Deploy Preview + รัน Journey ครบบน Test Branch
4. เริ่ม Cycle ใหม่บน Lab หลัก (Reset ต้องอนุมัติแยก) — ห้ามรัน Final ต่อบน Cycle ที่เคยใช้ v1

**Rollback:** ถอด `CLASSROOM_SOURCE_VERSION`; `DROP SCHEMA demo_ml CASCADE` และ Drop ตาราง `dq_*`/`published_snapshot` ได้ (ไม่แตะ ER1/ER2); พลิก Deploy กลับ Commit เดิม
