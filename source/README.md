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
- **การสาธิต Error ในเดือนที่ 3 (incremental_02_error)**:
  - ในเดือนที่ 3 (มีนาคม) มีชุดข้อมูลจำลองแบบพิเศษ `incremental_02_error` เพื่อสาธิตกรณีข้อมูลผิดกฎคุณภาพ (เช่น มี SKU ที่ไม่เคยลงทะเบียนใน `Dim_SKU`)
  - ระบบจะตรวจพบในขั้นตอน **Transform / Quality Check** และทำการกักข้อมูล (Quarantine) ไว้ โดยไม่ส่งข้อมูลที่ผิดพลาดเข้าสู่ **ตาราง Warehouse**
  - ผู้ใช้สามารถกดปุ่ม *"รันต่อด้วยข้อมูลฉบับแก้ไข"* เพื่อดึงชุดข้อมูลปกติของเดือน 3 และรันต่อจาก Checkpoint ได้อย่างราบรื่น

---

## 3. การแยกคำศัพท์ให้ถูกต้อง (Terminology Standards)

- **ไฟล์ CSV (CSV File)**: ไฟล์ข้อความต้นทางสำหรับนำเข้า
- **ตาราง Database (Database Table)**: ตารางเชิงสัมพันธ์ใน Neon PostgreSQL (`demo_er1`) หรือ SQLite
- **ชุดข้อมูล/ไฟล์ Data Lake (Data Lake Parquet)**: ไฟล์ Parquet ที่จัดเก็บแบบ Columnar (แยกชั้น `raw` และ `standardized`)
- **ตาราง Warehouse (Warehouse Table/Mart)**: ตารางมิติและ Fact ใน DuckDB (`er2.duckdb`) สำหรับแสดงผล KPI บน Dashboard
