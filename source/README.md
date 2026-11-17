# Source สำหรับ Classroom Demo

Source เป็นข้อมูลสังเคราะห์เพื่อการศึกษาเพื่อสาธิต Data Pipeline ตั้งแต่ต้นทางจนถึงปลายทาง

ชุดข้อมูลที่ใช้ใน Colab และหน้า Test Pipeline บน Vercel คือ **Source รายเดือนมกราคม–ตุลาคม 2569** จำนวน 10 ชุด โดยแต่ละชุดประกอบด้วย **ไฟล์ CSV ทั้งหมด 21 ไฟล์** ตามโครงสร้างสัญญาข้อมูล (Data Contract) ER1 เดียวกัน

[ดาวน์โหลด Source ZIP ทั้ง 10 เดือน](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/releases/tag/classroom-source-v1) · [ดูตัวสร้าง Source รายเดือน](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/pipeline/generate_classroom_source.py) · [ดู Schema](../schemas/)

---

## 1. รายชื่อไฟล์ CSV ต้นทาง 21 ไฟล์ และการแปลงเป็น 25 ตารางใน Database

ต้นทางในแต่ละรอบเดือนรับเข้าเป็น **ไฟล์ CSV 21 ไฟล์**:
1. `Fact_Orders.csv` (หัวคำสั่งซื้อ)
2. `Fact_Order_Items.csv` (รายการสินค้าในคำสั่งซื้อ)
3. `Fact_Internal_Fulfillment.csv` (การจัดส่งภายใน)
4. `Fact_Marketing_Costs.csv` (ต้นทุนการตลาด)
5. `Fact_Free_Samples.csv` (สินค้าตัวอย่าง)
6. `Fact_Claim_Header.csv` & `Fact_Claim_Details.csv` (การเคลมสินค้า)
7. `Fact_Goods_Receipt.csv` & `Fact_Goods_Receipt_Items.csv` (การรับสินค้า)
8. `Dim_SKU.csv`, `Dim_Product_Group.csv`, `Dim_Campaign.csv`, `Dim_Ad_Campaign.csv`, `Dim_Creator.csv`, `Dim_Voucher.csv` (มิติข้อมูล)
9. `Bridge_Campaign_Product_Group.csv`, `Bridge_Voucher_Product_Group.csv` (ตารางเชื่อมโยง)
10. `Ref_Business_Target.csv`, `Ref_Cost_Policy.csv`, `Ref_Platform_Fee_Estimate_Rules.csv`, `Ref_Affiliate_Commission_Rules.csv` (ตารางอ้างอิงและนโยบาย)

> **ทำไมโหลดเข้า Database กลายเป็น 25 ตาราง?**
> เมื่อนำเข้าสู่ **ตาราง Database (Neon PostgreSQL / SQLite)** Pipeline จะสร้างตารางคำนวณและบริหารคลังเพิ่มเติม 4 ตาราง ได้แก่:
> - `Fact_FIFO_Allocation` (การจัดสรรต้นทุนแบบเข้าก่อนออกก่อน)
> - `Fact_Order_Platform_Fees` (ค่าธรรมเนียมแพลตฟอร์มตามกฎอ้างอิง)
> - `Fact_Stock_Movement` (ความเคลื่อนไหวสินค้าในคลัง)
> - `Fact_Inventory_Snapshot` (ยอดคงเหลือสินค้าประจำงวด)
> รวมเป็น **25 ตาราง Database** ในสคีมา `demo_er1`

---

## 2. ลำดับการรันรายเดือน (มกราคม–ตุลาคม 2569)

- **Run 1 (initial)**: นำเข้าข้อมูลเดือนมกราคม 2569 (บันทึก Master/Dimension และ Transaction ประจำเดือน)
- **Run เติมข้อมูล (incremental_01 ถึง incremental_09)**: เติมข้อมูลเดือนกุมภาพันธ์ถึงตุลาคม 2569 ทีละ 1 เดือนตามลำดับ โดยไม่ทับข้อมูลเดิม
- **Final Main Flow (Source version `classroom_v2_2026_11_16`)**: เดือนมีนาคมใน Source หลักมีแถวที่ `Fact_Order_Items.SKU_ID` ไม่มีใน `Dim_SKU` อยู่ **1 แถวโดยตั้งใจ** (ไม่มี Error อื่นใน Main Flow) ระบบตรวจด้วยกฎทั่วไป `REFERENCE_EXISTS` ที่สร้างจาก `Ref:` ใน `schemas/ER1_V3.dbml` ไม่ผูกกับเดือน, Batch หรือรหัส SKU ใด ๆ
  - **Stage 1 (Source → ER1)**: อ่าน CSV เข้า Staging → ตรวจ DQ ทุกแถว → Promote เข้า ER1 ได้เมื่อผ่านเท่านั้น ถ้าไม่ผ่านจะไม่มีข้อมูลเดือนนั้นเข้า ER1 และ Run เป็น `BLOCKED_DQ`
  - **Stage 3** ตรวจซ้ำด้วยกฎชุดเดียวกัน (Defense in Depth) ก่อนสร้างข้อมูล Standardized
  - Issue, Rule Result, Correction (Append-only, มี Version) และ Revalidation เก็บใน Neon `demo_control.dq_*` (ต้อง Apply `sql/neon_dq_recovery_migration.sql` ก่อน) Review & Fix อ่านจากฐานข้อมูลจริง ระบบไม่เลือก SKU ให้และไม่เติมเหตุผลให้
  - Revalidate ใช้กฎเดิมกับแถวต้นฉบับ + Correction แล้ว Resume รันเดือนนั้นใหม่ตั้งแต่ Stage 1; ไฟล์ CSV/ZIP ต้นฉบับไม่ถูกแก้ และเดือนที่ Publish แล้วไม่ถูกแตะ
  - Source ถูกล็อกด้วย SHA-256 ของ ZIP ทั้ง 10 เดือน (`dashboard/data/source_lock_classroom_v2.json`) ตรวจก่อนเขียนข้อมูลทุกครั้ง ทั้ง Run Next Step และ Run All ค่าเริ่มต้นของระบบยังเป็น Release เดิม `classroom-source-v1` จนกว่าจะตั้ง `CLASSROOM_SOURCE_VERSION` (ดู `docs/DQ_RECOVERY_RUNBOOK_TH.md`)
  - ห้ามใช้ Source ชุดเดิม (`H2026…`) ปนกับชุด Final (`ORD-2026…`) ใน Cycle เดียวกัน (Worker จะปฏิเสธด้วย `LAB_SOURCE_VERSION_MIXED`)
  - ตัวแปร `incremental_02_error` เป็นของชุดเดิม (v1) เท่านั้น ไม่ใช่ส่วนของ Final Main Flow
  - ไฟล์ใน `qa_only/` ของแพ็กเกจ Final ใช้เป็นเฉลยสำหรับ Test เท่านั้น ห้ามเป็น Runtime Input หรือคำตอบอัตโนมัติ

---

## 3. การแยกคำศัพท์ให้ถูกต้อง (Terminology Standards)

- **ไฟล์ CSV (CSV File)**: ไฟล์ข้อความต้นทางสำหรับนำเข้า
- **ตาราง Database (Database Table)**: ตารางเชิงสัมพันธ์ใน Neon PostgreSQL (`demo_er1`) หรือ SQLite
- **ชุดข้อมูล/ไฟล์ Data Lake (Data Lake Parquet)**: ไฟล์ Parquet ที่จัดเก็บแบบ Columnar (แยกชั้น `raw` และ `standardized`)
- **ตาราง Warehouse (Warehouse Table/Mart)**: ตารางมิติและ Fact ใน DuckDB (`er2.duckdb`) สำหรับแสดงผล KPI บน Dashboard
