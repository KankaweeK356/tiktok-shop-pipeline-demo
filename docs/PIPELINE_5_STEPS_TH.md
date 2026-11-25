# Pipeline 5 ขั้น — อธิบายละเอียดสำหรับอาจารย์ (ตรวจกับโค้ดจริง)

ภาพรวมจำนวนตาราง (ไหลจากซ้ายไปขวา)

```
Source CSV 21 ไฟล์ ──► ER1 (Postgres) 25 ตาราง ──► Lake Raw Parquet 25 ไฟล์
   ──► Lake Standardized 10 ตาราง (+ claim_daily_external) ──► ER2 (DuckDB) 11 ตาราง + 1 View
```

หลักคิด: ER1 = OLTP (normalized) · Lake = เก็บดิบ/มาตรฐาน · ER2 = Star schema สำหรับวิเคราะห์ (ลดจาก 25 → 11 เพราะ Warehouse เก็บเฉพาะ "ที่ใช้วิเคราะห์" ตามหลัก Dimensional ของ Ch.5)

หมายเหตุ: ทุกขั้นทำเป็น Checkpoint (ขั้นที่สำเร็จแล้วไม่ถูกรันซ้ำ), ถ้าล้มเหลวจะเขียน error report + quarantine ไว้ใน `lake/governance/quarantine` และ Resume ต่อได้

---

## ขั้น 1 — Ingest: Source (CSV) → ER1 Database

**Input:** ZIP ของเดือนนั้น ตรวจ SHA-256 กับ Source Lock ก่อน (ถ้า hash ไม่ตรง = ไม่รับ)

**Source 21 ตาราง**
- Master / Reference 12 ตาราง: Dim_Product_Group, Dim_SKU, Dim_Creator, Dim_Campaign, Dim_Ad_Campaign, Dim_Voucher, Bridge_Campaign_Product_Group, Bridge_Voucher_Product_Group, Ref_Affiliate_Commission_Rule, Ref_Platform_Fee_Estimate_Rule, Ref_Business_Target, Ref_Cost_Policy
- Transaction 9 ตาราง: Fact_Goods_Receipt, Fact_Goods_Receipt_Items, Fact_Orders, Fact_Order_Items, Fact_Internal_Fulfillment, Fact_Marketing_Costs, Fact_Claim_Header, Fact_Claim_Details, Fact_Free_Samples
- เดือนแรก (initial) ต้องมีครบทั้ง 21 ไฟล์ เดือนถัดไปต้องมีอย่างน้อย 5 ไฟล์ธุรกรรมรายเดือน: Fact_Orders, Fact_Order_Items, Fact_Internal_Fulfillment, Fact_Marketing_Costs, Fact_Free_Samples (ขาดไฟล์ → error `E02_MISSING_SOURCE`)

**ทำอะไร (เรียงลำดับ)**
1. อ่าน CSV เข้า staging ในหน่วยความจำ (ไฟล์ต้นฉบับไม่ถูกแก้)
2. **DQ Gate ด่านที่ 1** — ตรวจกฎ 92 ข้อที่สร้างอัตโนมัติจาก schema ER1:
   - PK_UNIQUE 21 ข้อ: คีย์หลักของแต่ละตารางต้องไม่ซ้ำ
   - NOT_NULL 50 ข้อ: คอลัมน์ที่ต้องมีค่าต้องไม่ว่าง
   - REFERENCE_EXISTS 21 ข้อ: Foreign key ต้องมีแม่จริง (เช่น SKU ใน Order_Items ต้องมีใน Dim_SKU)
   - ถ้ามีข้อใดตก (BLOCKING) → หยุด ไม่เขียนอะไรเข้า ER1 เลย (ตัวอย่างสด: มีนาคมมี SKU ไม่มีใน Dim_SKU)
3. เปิด transaction แล้ว upsert ทุกตารางเข้า ER1 (รันซ้ำเดือนเดิมไม่ซ้ำซ้อน = idempotent)
4. กฎธุรกิจ: ออเดอร์ที่จ่ายแล้วแล้วกลับเป็น Cancelled → `T03_REFUND_OUT_OF_SCOPE` (Demo ไม่รองรับ refund)
5. **คำนวณ** ต้นทุนรายออเดอร์ (calculate_orders: ส่วนลด voucher กระจายตามสัดส่วน, ค่า affiliate ตามอัตรา Product Group) และ **FIFO allocation** ตัดล็อตสต็อกเก่าก่อน (Fact_FIFO_Allocation) + Inventory snapshot / Stock movement / Order platform fees
6. ตรวจ Foreign-key integrity ทั้งฐาน (`E01_INTEGRITY`) แล้ว COMMIT

**Output:** ER1 = **25 ตาราง** (21 source + 4 derived: Fact_Inventory_Snapshot, Fact_Stock_Movement, Fact_Order_Platform_Fees, Fact_FIFO_Allocation) + ไฟล์ `changes_<batch>.json` บอกว่าเดือนนี้ order/ad/sample ใดเปลี่ยน (เอาไว้ทำ incremental ต่อ)
ตัวอย่างเดือน ต.ค.: Fact_Orders 900 แถว

---

## ขั้น 2 — Extract: ER1 → Data Lake (Raw)

**Input:** ER1 (Neon Postgres)

**ทำอะไร**
1. คัดลอกไฟล์ CSV ต้นฉบับเก็บที่ `landing/` พร้อม SHA-256 (หลักฐานว่าดิบไม่ถูกแก้)
2. อ่านทุกตารางใน ER1 (`SELECT *` ครบ **25 ตาราง**) เขียนเป็น Parquet ที่ `raw/<batch>/`
3. เขียน manifest (ชื่อไฟล์, จำนวนแถว, sha256 ต่อตาราง) และ schema receipt (รายชื่อคอลัมน์)

**Output:** 25 ไฟล์ Parquet (snapshot เต็มของ ER1 ณ เวลานั้น) + manifest + schema receipt
แนวคิด: ตรงกับ Ch.4 Data Lake — แยกโซน landing → raw และเก็บ lineage/hash ได้ ส่วนการเลือกเฉพาะข้อมูลที่เปลี่ยนเกิดตอน Transform (ใช้ `changes_<batch>.json`)

---

## ขั้น 3 — Transform: Raw → Standardized + Data Quality

**Input:** Raw Parquet 25 ไฟล์

**ทำอะไร**
1. **DQ Gate ด่านที่ 2 (defense in depth):** ตรวจกฎชุดเดียวกัน 92 ข้อซ้ำบน Raw snapshot — ถ้ามีข้อมูลไม่ผ่านจะไม่มีทางไปถึง Warehouse แม้ด่านแรกถูกข้าม
2. ตรวจ **กฎธุรกิจ** ระหว่างแปลงข้อมูล (error code):
   - `T02_CAMPAIGN_OVERLAP` แคมเปญ Active ของกลุ่มสินค้าเดียวกันซ้อนช่วงเวลากัน
   - `T01_VOUCHER` voucher ที่หักต้องไม่ติดลบ/ไม่เกินยอดขาย
   - `T05_FEE_POLICY` ค่าธรรมเนียมแพลตฟอร์มต้องเป็น fixed 10%
   - `T06_MISSING_COGS` ต้นทุนสินค้าต้อง > 0
   - `T06_AFFILIATE_WITHOUT_CREATOR` ค่า affiliate ต้องมี creator
   - `T07_UNKNOWN_GROUP` ads ต้องอ้างกลุ่มสินค้าที่มีจริง
3. **จัดมาตรฐาน/แปลงเป็นโครง Star schema:**
   - สร้าง Surrogate key (Product_Key, Creator_Key, Voucher_Key, …) แทน business key; Creator/Voucher "ไม่มี" ใช้ key 0 = Not Applicable
   - รวมหลายตาราง ER1 (Orders + Order_Items + Fulfillment + SKU + Group) เป็นแถว **ระดับ Order Item เดียว** (Fact_Sales_Order_Item)
   - แปลงวันที่เป็น Date_Key (YYYYMMDD) โดยยอดขายนับตาม `Paid_At`, ราคา lock ณ `Order_Created_At`
   - คำนวณ: Net_Revenue = ยอดขายหลังแคมเปญ − voucher; Platform fee = 10% × Net; ค่าขนส่งกระจายตามสัดส่วน Net (เศษสตางค์ไปที่บรรทัดสุดท้าย); Contribution (ก่อน Ads/Sample/Claim) = Net − COGS − Fee − Fulfillment − Affiliate
   - Ads ถือระดับ วัน × กลุ่มสินค้า ไม่ join ลง SKU โดยตรง (กันบิดเบือนยอด)
   - เก็บเฉพาะรายการที่เปลี่ยนในเดือนนี้ (incremental)
4. เขียน lineage.csv ทุกแถว (ไฟล์ต้นทาง → ER1 → Raw → Standardized → ER2) และ allocation_audit (อธิบายสูตรที่ใช้)

**Output:** Standardized Parquet **10 ตาราง**: Dim_Date, Dim_Product, Dim_Creator, Dim_Ad_Campaign, Dim_Voucher, Dim_Cost_Basis, Fact_Sales_Order_Item, Fact_Ads_Daily, Fact_Free_Sample, Fact_Business_Target_Monthly + `claim_daily_external` (ค่า claim รายวัน×กลุ่ม) + dirty_dates_groups + lineage
ตัวอย่างเดือน ต.ค.: อ่าน Order_Items 1,330 แถว → ได้แถว Sales ที่เปลี่ยน 183 แถวในเดือนนี้ (เหลือเฉพาะรายการ Paid ที่เปลี่ยน)

---

## ขั้น 4 — Load: Standardized → Data Warehouse (ER2 DuckDB) + Mart

**Input:** Standardized Parquet

**ทำอะไร**
1. เปิด transaction เดียว (ล้มกลางทางต้อง ROLLBACK ทั้งหมด — มี test inject `L01`)
2. Upsert **Dimension 6 ตารางก่อน** แล้ว **Fact 4 ตาราง** (กัน FK เสีย) โดยใช้ business key เดิมให้ได้ surrogate key เดิม รันซ้ำไม่ซ้ำแถว
3. สร้าง/อัปเดต **Mart_Product_Group_Daily_Performance** ใหม่เฉพาะ (วัน × กลุ่ม) ที่เปลี่ยน (รวม Net, COGS, ค่าธรรมเนียม, Ads, Sample, Claim, Contribution Profit)
4. สร้าง **View_Shop_Monthly_KPI** (KPI รายเดือน: Gross, Net, Profit, Profit protection)

**Output:** ER2 = **11 ตาราง** (Dim 6 + Fact 4 + Mart 1) + 1 View
ตัวอย่างเดือน ต.ค.: Fact_Sales_Order_Item สะสมในคลัง 1,147 แถว

---

## ขั้น 5 — Validate: ตรวจ ER1 ↔ ER2 (Reconciliation) + Lineage

**Input:** ER1 + ER2 (อ่านอย่างเดียว)

**ตรวจอะไร (ผลเดือน ต.ค. = 21 ข้อ ผ่านทั้งหมด)**
1. ER1 มี 25 ตาราง และ ER2 มี 11 ตาราง ตามสัญญา schema; Foreign-key check ไม่พบข้อผิดพลาด
2. **เทียบยอดต้นทาง vs คลัง:** จำนวน item ที่จ่ายแล้ว, Net Revenue, Gross, COGS, Affiliate (ตัวอย่าง: 1,147 = 1,147 แถว; Net Revenue 417,092.85 = 417,092.85)
3. ไม่มี Order Item ซ้ำในคลัง
4. ผลรวม voucher ต่อออเดอร์ตรงกับที่ลดจริง
5. ตรวจสูตรทุกแถว: Net = ขายหลังแคมเปญ − voucher, Fee = 10% ของ Net, Gross = จำนวน × ราคาฐาน
6. Fact → Mart ยอดตรงกัน (Net, Ads, Sample, Claim) และ Mart profit = ผลรวมองค์ประกอบ
7. ต่อเดือนใน View KPI: Profit protection required/headroom/status คำนวณถูกต้อง
8. **Lineage:** สุ่มตามรอย 8 รายการจาก CSV → ER1 → Lake Raw → Standardized → ER2 → Mart

ถ้ามีข้อใดไม่ผ่าน → โยน error ไม่ให้ Publish

**Output:** รายงาน `functional_<batch>.csv/json` + `lineage_<batch>.csv` → ผ่านครบจึงกด **Publish Snapshot** ให้ Dashboard เห็นเดือนนั้น (เดือนที่ยังไม่ Publish ไม่ถูกใช้ใน Forecast)

---

## สรุปให้อาจารย์ใน 30 วินาที
"ข้อมูลเดือนละ 21 ไฟล์ผ่านด่านตรวจ 92 กฎก่อนเข้า ER1 (25 ตาราง) → ดึงเป็น Parquet ดิบ 25 ไฟล์ → แปลงเป็นโครง Star เหลือ 10 ตารางมาตรฐาน พร้อมคำนวณต้นทุน/กำไรทีละบรรทัด → โหลดเข้า Warehouse 11 ตาราง + Mart + View → เทียบยอดต้นทาง/ปลายทาง 21 ข้อก่อนปล่อยให้ Dashboard ใช้ ทุกขั้นมี checkpoint, ล้มแล้ว resume ได้, และตามรอยย้อนกลับถึงไฟล์ต้นทางได้"
