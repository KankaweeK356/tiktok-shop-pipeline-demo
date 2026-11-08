# Neon ER1 — Classroom Run 1 / Run 2 / Replay / Clear

## สถานะที่สร้างจริง (2026-11-08)
- Neon Project: `tiktok-shop-is-pipeline-demo` (Free)
- Project ID: `hidden-leaf-09169842`
- Database: `tiktok_demo`, PostgreSQL 17, Branch: `main`
- Schema: `demo_er1` มี **25 Business Tables** จาก `schemas/ER1_V3.dbml`, **26 Foreign Keys**
- Schema: `demo_control` มี **6 Metadata Tables** แยกจาก Business ER1
- ER1 Data: ยังไม่มี Orders/ธุรกรรมถูกโหลด, `dataset_state`: cycle=1, phase=EMPTY
- Bootstrap DDL ที่ใช้ทำซ้ำได้: `sql/neon_er1_demo_bootstrap.sql`
- **ยังไม่ได้ต่อ Neon เข้ากับ Runner หรือ Vercel**; โค้ดเดิมยังใช้ SQLite สำหรับ ER1

## ขอบเขต Demo ที่ต้องรักษา

| Action จาก Web App | Preconditions | ผลลัพธ์ที่ต้องพิสูจน์ |
| --- | --- | --- |
| **Run 1 — Initial** | phase=EMPTY และไม่มี job RUNNING | โหลด Source ตั้งต้นลง **Neon ER1 ของ Cycle นี้**; สร้าง Lake Landing/Raw/Standardized และ DuckDB ER2; ตรวจยอด/Lineage PASS; จบ phase=RUN1_READY |
| **Run 2 — Incremental** | phase=RUN1_READY | เพิ่ม New Orders/Items, อัปเดต Pending→Paid และข้อมูลที่เปลี่ยนใน **Neon ER1 เดิม**; ส่ง Changed Data ไป Lake และ ER2 เดิม; ยอดหลัง Run 2 ต้องเปลี่ยนตามจริง; จบ phase=RUN2_READY |
| **Replay** | phase=RUN2_READY | ใช้ `request_key` และ Source Digest ของ Batch 2 เดิม; ไม่สร้างยอดซ้ำ, ตรวจ Business Signature ก่อน/หลังเท่ากัน |
| **Error Recovery** | เป็น Workspace/Branch ทดสอบแยก | Inject Error → Log Stage Failure → Retry Stage ที่เหมาะสม; ห้ามทำลายข้อมูลหลักที่สาธิตอยู่ |
| **Clear Demo Data** | ผู้ดูแลยืนยัน + ไม่มี Active Run | ล้างเฉพาะข้อมูลของ Demo Cycle ใน `demo_er1` และล้าง Lake/DuckDB/รายงานใน Object Storage ภายใต้ Cycle เดียวกัน; เก็บ `demo_control` Audit และ Run History; cycle+=1 และ phase=EMPTY |
| **Run 1 อีกครั้ง** | หลัง Clear สำเร็จแล้ว | เริ่มชุดใหม่ได้จริง โดยไม่ต้องสร้าง DB Tables หรือ Neon Project ใหม่ |

**ไม่ควรกด Clear แล้ว DROP TABLE หรือ DROP SCHEMA** เพราะจะทำให้ ER Diagram, Constraints และสิทธิ์การเข้าถึงหายไปพร้อมกัน

## กลไกสำคัญในการเชื่อม Neon

### 1. Migrating ER1
- PostgreSQL schema ใช้ชื่อคอลัมน์ตัวใหญ่ตาม DBML เดิมแบบ Quoted Identifiers
- Decimal เป็น NUMERIC(20,4), Date/Time เป็น DATE/TIMESTAMP, Boolean เป็น BOOLEAN
- Primary Keys/Foreign Keys สร้างตาม DBML จริง; ไม่เพิ่ม Metadata ลงใน Business ER1
- `pipeline/er1.py` ปัจจุบัน **SQLite-specific** มี SQL สไตล์ `?`, `INSERT OR IGNORE`, `INSERT OR REPLACE`, `date(?)` และการใช้ Transaction ผ่าน sqlite3 จึง **ยังไม่สามารถเปลี่ยนแค่ URL** ให้ต่อ Neon ได้
- ต้องสร้าง PostgreSQL ingest adapter พร้อม regression tests เพื่อรักษา Price/Voucher/FIFO/Cost logic และทำให้ธุรกรรมราย Batch เป็น Atomic
- `pipeline/lake.py` ปัจจุบัน Extract จาก SQLite ต้องเปลี่ยนเพื่ออ่าน PostgreSQL Snapshot เมื่อเลือก Cloud Mode

### 2. Data Lake / Warehouse
- Neon PostgreSQL เป็น ER1 ไม่ได้แทน Data Lake หรือ DuckDB Warehouse
- แนะนำ Object Storage สำหรับไฟล์ `{cycle}/lake/landing,raw,standardized`, `{cycle}/warehouse`, `{cycle}/reports`
- DuckDB เป็น Engine ใน Runner; ถ้าต้องการแสดง Warehouse ข้ามรอบต้องเก็บ Artifact ที่ตรวจสอบ Checksum แล้วลง Storage
- `demo_control.pipeline_artifacts` เก็บ URI + SHA256 + จำนวนแถว เป็น Metadata/Lineage ไม่ใช่เนื้อหา Parquet
- ต้องใช้ Version/Cycle ID ในทุก Artifact เพื่อไม่ให้ผลเก่าปนกับ Run ใหม่

### 3. Concurrency, Idempotency และ State
- ทุกคำสั่งมาจาก Authenticated Backend เท่านั้น (ไม่ใส่ Neon/GitHub Token ใน JS Frontend)
- Lock `demo_control.dataset_state` ด้วย Transaction + `SELECT ... FOR UPDATE` ก่อนเริ่ม Run หรือ Clear
- บังคับ State Machine: `EMPTY→RUN1_READY→RUN2_READY` และ Replay คง `RUN2_READY`
- `pipeline_runs` มี `request_key` Unique ตาม `dataset_key+cycle_number+run_type` ป้องกัน Double Click/Retry Request
- Run สำเร็จได้เมื่อ Stage ทุกขั้นผ่านและ Reconciliation PASS
- Failed run ต้องไม่เปลี่ยน Phase เป็น READY; Log ลง `stage_runs` และ `stage_events` เพื่อ Retry/ตรวจสอบ
- **GitHub Actions Runner ไม่ใช่บริการถาวร**; ควรบันทึกสถานะและ Artifact ที่ Neon + Object Storage เพื่อให้ Web App ดูย้อนหลังได้

### 4. Clear/Reset ที่ปลอดภัย (ยังไม่ได้เชื่อมใช้งาน)
1. UI ให้ผู้ใช้พิมพ์ยืนยัน `CLEAR DEMO` พร้อมสรุปว่าข้อมูลอะไรจะถูกล้าง
2. Backend ตรวจสิทธิ์ผู้ดูแล + ตรวจไม่มี Run ที่สถานะ QUEUED/RUNNING
3. Lock Dataset State และกำหนด Cycle ที่ต้องเคลียร์ให้แน่นอน ป้องกัน Race
4. ล้าง Business Rows ทั้ง 25 ตารางด้วย SQL ที่ Scope เฉพาะ `demo_er1` อย่างชัดเจน ภายใน Database Transaction
5. ลบ Object Storage Prefix ของ Cycle เดิม (Lake, Warehouse, Reports) หลังตรวจสิทธิ์/Prefix; ถ้าลบไม่สำเร็จ ห้ามรายงาน Reset Success และต้องมีวิธี Retry/Cleanup
6. บันทึก `reset_audit` และเพิ่ม Cycle Number พร้อมเปลี่ยน phase=EMPTY เมื่อจบทั้ง DB และ Storage แล้ว
7. เริ่ม Run 1 ใหม่โดยใช้ Cycle Number ใหม่; รักษาโครงสร้าง ER1 ทั้งหมดเหมือนเดิม

**หมายเหตุทางเทคนิค:** Database Transaction ครอบคลุม Object Storage ไม่ได้ จึงต้องใช้ Reset Orchestrator แบบมีสถานะและกลไก Retry ที่สามารถกู้คืนได้ ไม่ควรให้ Frontend ยิง SQL TRUNCATE โดยตรง

## สิ่งที่ทดสอบยืนยันใน Neon แล้ว
- Query `information_schema.tables`: demo_er1 25, demo_control 6
- Foreign Keys: 26
- `demo_control.dataset_state`: phase=EMPTY, cycle_number=1
- `demo_er1."Fact_Orders"`: 0 Rows

## ยังไม่ทดสอบ / ยังไม่เสร็จ
- การ Import Mock CSV เข้า Neon และใช้ PostgreSQL เป็น ER1 หลัก
- Run 1, Run 2, Replay, Clear กับ PostgreSQL/Storage จริง
- Web App `Pipeline Demo` ที่กดแล้วสั่ง GitHub Actions ผ่าน Backend API
- Cloud Storage สำหรับ Parquet/DuckDB และการ Cleanup แบบ End-to-End

**ดังนั้น Schema ตอนนี้รองรับทุก Scenario เชิงโครงสร้างแล้ว แต่ยังต้องพัฒนา Cloud Mode ของ Pipeline และรันทดสอบ End-to-End ก่อนอ้างว่าใช้ได้ครบจริง**

## หลักการเลือก Test Data
ตอนพัฒนาให้ใช้ Mock Profile เดิม (Initial/Incremental) และ Seed เดิมก่อน ไม่เปลี่ยนยอดขายเพื่อให้ CI ผ่าน เมื่อสำเร็จค่อยเพิ่ม Profile 12 เดือนสำหรับ ML เป็นการทดสอบแยก โดยยังคง Batch Demo ไม่บวม
