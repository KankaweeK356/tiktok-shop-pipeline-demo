# ก่อน / หลัง: ข้อความในหน้า "ทดสอบการนำเข้าข้อมูล" (5 ขั้น × 5 แท็บ)

> เอกสารข้อเสนอ ยังไม่ได้แก้ระบบ "ก่อน" = ที่แสดงบนหน้าจอตอนนี้ (อ่านจากโค้ด) · "หลัง" = ข้อเสนอ
> ตัวอย่างตัวเลข: ผลรันจริงที่เก็บใน repo (ออเดอร์ 900, Sales 183 แถว, คลัง 1,147 แถว, ตรวจ 21/21) และตัวเลข 2,135 จากภาพหน้าจอรอบที่คุณแคปมา ตัวเลขจริงตอน Demo จะต่างตามรอบที่รัน

## หลักการใหม่ที่ใช้ทุกหน้า

1. **ป้ายตัวเลขบอกว่านับอะไร** แทนคำว่า "Output records" ที่ความหมายเปลี่ยนทุกขั้น
2. **ทุกกล่องมีป้ายแหล่งที่มา:** 🟢 **หลักฐานรอบนี้** (ตัวเลข/ตัวอย่างจากการรันจริง) หรือ ⚪ **คำอธิบายขั้นตอน** (มาตรฐานของระบบ ไม่ใช่ผลเฉพาะรอบ)
3. **ไม่อ้างสิ่งที่โค้ดไม่ได้ทำ** (ตัด read-only, SSL, แปลง timezone, zero-copy, approval)
4. **ขั้นที่ไม่มีกฎ DQ ก็บอกตรง ๆ** ว่า "ขั้นนี้ไม่มีกฎ DQ"

---

## ป้ายตัวเลขในแท็บ Preview

| ขั้น | ก่อน | หลัง |
|---|---|---|
| Ingest | Output records **900** | ออเดอร์สะสมใน ER1 (Fact_Orders) **900** |
| Extract | Output records **2,135** | ออเดอร์ใน Raw snapshot (Fact_Orders) **2,135** |
| Transform | Output records **183** | แถวยอดขายที่เปลี่ยนในเดือนนี้ (Fact_Sales_Order_Item) **183** |
| Load | Output records **1,147** | แถวยอดขายสะสมใน Warehouse **1,147** |
| Validate | Output records **21** | ข้อตรวจทั้งหมด **21** (ผ่าน 21 · ไม่ผ่าน 0) |
| ทุกขั้น | "ผลจาก GitHub Worker ที่ประมวลผลใหม่" | "ผลจากการรันจริงบน Vercel Worker" |

---

## ขั้น 1 — Ingest (CSV → ER1)

### แท็บ Process

| ก่อน (6 ข้อ) | หลัง (8 ข้อ) |
|---|---|
| 1. Read & Verify Source ZIP — "หลักฐานจริง: Verified SHA-256 Checksum" | 1. ตรวจสถานะและลำดับ: ต้องอยู่ในสถานะที่ถูก และเดือนก่อนต้อง Validate ผ่านแล้ว |
| 2. Parse & Standardize CSV | 2. อ้างอิงข้อมูลยืนยัน Source (Source Lock) และสร้าง Run ใน `demo_control` |
| 3. Load Local ER1 SQLite | 3. อ่าน CSV เข้า staging ในหน่วยความจำ (ไฟล์ต้นฉบับไม่ถูกแก้) |
| 4. Generate Derived ER1 Tables | 4. **ตรวจ DQ 92 กฎ — ถ้าตกข้อใดหยุดทั้งเดือน ยังไม่เขียนอะไรเข้า ER1** *(ขั้นนี้คือที่เดือนมีนาคมถูกบล็อก)* |
| 5. Sync & Reconcile to Neon | 5. upsert เข้า `er1.sqlite` ใน transaction เดียว |
| 6. Record Checkpoint (S3) | 6. คำนวณ voucher, ค่าธรรมเนียม, affiliate, FIFO → สร้าง 4 ตาราง derived |
| | 7. ตรวจ Foreign Key ทั้งฐาน แล้ว COMMIT |
| | 8. ซิงก์ 25 ตารางเข้า Neon `demo_er1` แบบ atomic, บันทึกสถานะใน `demo_control`, เก็บ workspace เป็น zip ใน Object Storage |

ก่อน: ทุกบรรทัดมีป้าย "หลักฐานจริง: …" แม้เป็นแค่คำอธิบาย
หลัง: แสดง "ระบบทำ: …" ทุกข้อ และ 🟢 "หลักฐานรอบนี้" เฉพาะข้อที่มีตัวเลขจริง เช่น ข้อ 4 "ตรวจ 92 กฎ ผ่าน 92 · แถวที่ตรวจ N" และข้อ 8 "Fact_Orders สะสม 900 ออเดอร์"

### แท็บอื่น

| แท็บ | ก่อน | หลัง |
|---|---|---|
| Input | ไฟล์ CSV ต้นทาง + ตัวอย่างแถว (ถ้าโหลดไม่ได้ใช้รายการตัวอย่างสำรองโดยไม่แจ้ง) | เหมือนเดิม + ถ้าใช้รายการสำรอง ติดป้าย ⚪ "ตัวอย่างประกอบ" |
| ตรวจสอบข้อมูล | ตาราง DQ จริง + ประโยค "รายการกฎด้านล่าง…" ทั้งที่ไม่มีรายการ | ตาราง DQ จริง (92 กฎ) + อธิบาย 3 ชนิดกฎ: คีย์ไม่ซ้ำ · ห้ามว่าง · ต้องอ้างถึงข้อมูลแม่ที่มีจริง (เช่น SKU ต้องมีใน Dim_SKU) ลบประโยคที่ไม่มีรายการ |
| Output | Query ตารางจาก Neon สด | เหมือนเดิม + หมายเหตุ "จำนวนแถวสะสมทุกเดือนที่โหลดแล้ว" |

---

## ขั้น 2 — Extract (ER1 → Lake Raw)

### แท็บ Process

| ก่อน (5 ข้อ) | หลัง (5 ข้อ) |
|---|---|
| 1. Connect to Neon "ผ่าน Read-only Transaction" — "SSL Connection Established" | 1. เชื่อม Neon (สคีมา `demo_er1`) |
| 2. "สตรีมแบบ micro-batch แบ่งพาร์ทิชันรายเดือน" | 2. คัดลอก CSV ต้นฉบับไป `landing/` พร้อมคำนวณ SHA-256 |
| 3. Convert to Parquet (Snappy) | 3. อ่านทั้งตาราง (`SELECT *`) ทีละตาราง ครบ 25 ตาราง (snapshot เต็ม ไม่แบ่งพาร์ทิชัน) |
| 4. "เขียนลง Object Storage `lake/raw/orders/`" | 4. เขียนเป็น Parquet ที่ `lake/raw/<batch>/` ในพื้นที่ทำงาน (หลังจบขั้นถูก zip เก็บใน Object Storage) |
| 5. "ตรวจสอบ SHA-256" `landing_manifest.json` | 5. **บันทึก** `manifest_<batch>.json` (จำนวนแถว, hash ต่อไฟล์) และ schema receipt |

### แท็บอื่น

| แท็บ | ก่อน | หลัง |
|---|---|---|
| Input | รายการ 25 ตาราง จำนวนแถว = **ค่าอ้างอิงเดือนมกราคม** (เช่น Fact_Orders **274**) | 🟢 25 ตารางที่อ่านจาก Neon รอบนี้ พร้อมจำนวนแถวจริง (เช่น Fact_Orders **2,135**) |
| ตรวจสอบข้อมูล | "ยังไม่มีผลตรวจคุณภาพข้อมูล…" | "**ขั้นนี้ไม่มีกฎ DQ**" + 🟢 ไฟล์ Parquet 25 = ตาราง 25 · ผลรวมแถว · hash บันทึกครบ |
| Output | ไฟล์สมมติ `raw_orders.parquet` (274 แถว, รหัส `ORD-202601-00001`) | 🟢 Parquet จริง 25 ไฟล์ เช่น `Fact_Orders.parquet` พร้อมตัวอย่าง 5 แถวจริง (รหัส `OCT00001`) |

---

## ขั้น 3 — Transform (Raw → Standardized)

### แท็บ Process

| ก่อน (5 ข้อ) | หลัง (6 ข้อ) |
|---|---|
| 1. อ่าน Raw Parquet ผ่าน "Arrow Stream Reader" | 1. **ตรวจ DQ 92 กฎซ้ำบน Raw** (ด่านที่ 2 กันข้อมูลผิดหลุดผ่านด่านแรก) |
| 2. "ปรับ Timezone UTC→Asia/Bangkok" — "All timestamps normalized to ICT" | 2. ตรวจกฎธุรกิจก่อนแปลง: แคมเปญของกลุ่มสินค้าเดียวกันห้ามซ้อนช่วงเวลา |
| 3. "ตรวจ Fact_Order_Items กับ Dim_SKU" | 3. สร้าง Dimension 6 ตาราง พร้อมรหัสตัวแทน (surrogate key) และแถว "ไม่ระบุ" (Key 0) |
| 4. "กักรายการที่ไม่ผ่านทันที" | 4. สร้างแถวยอดขาย (ระดับ 1 แถว = 1 ชิ้นในออเดอร์) เฉพาะออเดอร์ที่ชำระแล้วและเปลี่ยนในเดือนนี้ ตรวจ voucher ≤ ยอดขาย, ค่าธรรมเนียม 10%, COGS > 0, affiliate ต้องมีครีเอเตอร์ แล้วคำนวณ Net, ค่าธรรมเนียม, ค่าจัดส่งแบบกระจาย |
| 5. "สร้าง `standardized_orders.parquet`" | 5. สร้าง Ads รายวัน, ของแจกฟรี, เป้ายอดขายรายเดือน, ยอด claim รายวัน |
| | 6. เขียน Standardized Parquet + `lineage.csv` + บันทึกสูตรที่ใช้ — **ถ้าตกกฎจะหยุดทั้งเดือน ไม่ได้กักทีละแถว** |

### แท็บอื่น

| แท็บ | ก่อน | หลัง |
|---|---|---|
| Input | ไฟล์สมมติ `raw_orders.parquet` 274 แถว | 🟢 Raw Parquet จริงที่อ่านเข้ามา พร้อมจำนวนแถว (เช่น Fact_Order_Items **1,330**) |
| ตรวจสอบข้อมูล | ตาราง DQ จริง + ประโยค "รายการกฎด้านล่าง…" (ไม่มีรายการ) | 🟢 ผล DQ ด่านที่ 2 + ⚪ รายการกฎธุรกิจ T01–T07 พร้อมความหมายสั้น ๆ |
| Output | ไฟล์สมมติ `standardized_orders.parquet` | 🟢 Standardized Parquet จริง เช่น `Fact_Sales_Order_Item.parquet` (**183** แถวเดือนนี้) พร้อมตัวอย่างจริง |

---

## ขั้น 4 — Load (Standardized → Warehouse)

### แท็บ Process

| ก่อน (5 ข้อ) | หลัง (6 ข้อ) |
|---|---|
| 1. Initialize DuckDB | 1. เปิด DuckDB และสร้างโครง ER2 |
| 2. "Zero-copy Parquet scan" | 2. เริ่ม transaction เดียว (ล้มกลางทาง = ROLLBACK ทั้งหมด) |
| 3. สร้าง `Dim_Date, Dim_Product, Dim_SKU, Dim_Shop, Dim_Campaign` | 3. upsert Dimension 6 ตาราง: Dim_Date, Dim_Product, Dim_Creator, Dim_Ad_Campaign, Dim_Voucher, Dim_Cost_Basis |
| 4. สร้าง `Fact_Orders, Fact_Order_Items, Fact_Settlements` | 4. upsert Fact 4 ตาราง: Fact_Sales_Order_Item, Fact_Ads_Daily, Fact_Free_Sample, Fact_Business_Target_Monthly |
| 5. สร้าง `Mart_Daily_Shop_Performance`, `View_Monthly_Business_KPI` | 5. สร้าง Mart_Product_Group_Daily_Performance ใหม่เฉพาะวัน×กลุ่มที่เปลี่ยน |
| | 6. สร้าง View_Shop_Monthly_KPI แล้ว COMMIT |

### แท็บอื่น

| แท็บ | ก่อน | หลัง |
|---|---|---|
| Input | ไฟล์สมมติ `standardized_orders.parquet` | 🟢 Standardized Parquet จริงที่ใช้โหลด |
| ตรวจสอบข้อมูล | "ยังไม่มีผลตรวจคุณภาพข้อมูล…" | "**ขั้นนี้ไม่มีกฎ DQ**" + 🟢 transaction สำเร็จ · จำนวนแถวต่อตาราง |
| Output | "12 วัตถุ" แต่เป็นรายการสมมติ: Fact_Orders, Dim_SKU, **Dim_Shop, Dim_Seller** (ไม่มีจริง) | 🟢 12 วัตถุจริงใน DuckDB (11 ตาราง + 1 View) พร้อมจำนวนแถวและตัวอย่างจริง (Fact_Sales_Order_Item **1,147** แถว) |

---

## ขั้น 5 — Validate (กระทบยอด + Publish)

### แท็บ Process

| ก่อน (5 ข้อ) | หลัง (5 ข้อ) |
|---|---|
| 1. "เทียบจำนวนแถวระหว่าง Source CSV, Neon, Lake และ DuckDB" (4 ชั้น) | 1. เทียบ **ER1 กับ ER2**: จำนวน item ที่จ่ายแล้ว, Net Revenue, Gross, COGS, Affiliate |
| 2. Net Revenue ระดับเศษสตางค์ | 2. ตรวจไม่มี item ซ้ำ · voucher รวมตรง · สูตรทุกแถว (Net, ค่าธรรมเนียม 10%, Gross) · ยอมรับต่างได้ไม่เกิน 1 สตางค์ |
| 3. เทียบ COGS, ค่าโฆษณา, ค่าธรรมเนียม | 3. ตรวจ Fact → Mart (Net, Ads, Sample, Claim, กำไร) และเกณฑ์ profit protection รายเดือน |
| 4. **"Publication Approval"** | 4. สุ่มตามรอย lineage 8 รายการ: CSV → ER1 → Lake → ER2 → Mart |
| 5. Publish Warehouse Snapshot | 5. ถ้าผ่านครบ **เผยแพร่อัตโนมัติ** (ไม่มีขั้นอนุมัติ) บันทึก `published_snapshot` และส่งออกไฟล์ Warehouse |

### แท็บอื่น

| แท็บ | ก่อน | หลัง |
|---|---|---|
| Input | ตาราง "4 ชั้น" (Source, Neon, Lake, Warehouse) ส่วนใหญ่ขึ้น "—" | 🟢 ER1 เทียบ ER2: item ที่จ่ายแล้ว 1,147 = 1,147 · Net Revenue 417,092.85 = 417,092.85 |
| ตรวจสอบข้อมูล | "ยังไม่มีผลตรวจคุณภาพข้อมูล…" (ทั้งที่ขั้นนี้มีผลตรวจจริง) | 🟢 **21/21 ผ่าน** + ⚪ กลุ่มของการตรวจ (ยอดตรงกัน · สูตรถูก · Fact→Mart · กำไรรายเดือน) |
| Output | Published Snapshot + KPI เดือนล่าสุด | เหมือนเดิม |

หมายเหตุ: รายชื่อ 21 ข้อรายตัวยังแสดงไม่ได้ เพราะหลักฐานเก็บแค่จำนวนข้อ ต้องเพิ่มข้อมูลฝั่ง worker แยกเป็นงานหลัง Demo

---

## ผลต่อ Neon compute

ไม่เพิ่ม ข้อมูลใหม่ที่แสดงมาจากหลักฐานที่หน้าเว็บโหลดไว้แล้ว (ไฟล์ผลรันใน Object Storage) ไม่มีการเรียกฐานข้อมูลเพิ่ม
