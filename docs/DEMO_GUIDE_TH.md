# คู่มือเตรียม Demo วิชา MADT8102 (เสาร์ 28 พ.ย. 2026)

> เอกสารนี้สรุปจากโค้ดจริงใน repo + สไลด์อาจารย์ (Ch.1–7) + มคอ.3 ใช้ซ้อมพูด ไม่ได้แก้ระบบ

## 1. Pipeline 5 ขั้น — เข้า/ทำอะไร/ออกอะไร

**Source:** ZIP 10 เดือน (ม.ค.–ต.ค. 2026) เดือนละ 21 ไฟล์ CSV ตรวจ SHA-256 กับ `source_lock_classroom_v2.json` (ข้อมูลจำลองเพื่อการเรียน ไม่ใช่ข้อมูล TikTok จริง)

21 ตาราง แบ่งเป็น
- Master/Dimension/Reference (12): Dim_Product_Group, Dim_SKU, Dim_Creator, Dim_Campaign, Dim_Ad_Campaign, Dim_Voucher, Bridge_Campaign_Product_Group, Bridge_Voucher_Product_Group, Ref_Affiliate_Commission_Rule, Ref_Platform_Fee_Estimate_Rule, Ref_Business_Target, Ref_Cost_Policy
- Transaction/Fact (9): Fact_Goods_Receipt, Fact_Goods_Receipt_Items, Fact_Orders, Fact_Order_Items, Fact_Internal_Fulfillment, Fact_Marketing_Costs, Fact_Claim_Header, Fact_Claim_Details, Fact_Free_Samples

| # | ขั้น | Input | ทำอะไร | Output |
|---|------|-------|--------|--------|
| 1 | **Ingest** | ZIP เดือนนั้น (21 CSV) | ตรวจ hash, โหลดเข้า ER1 (OLTP) | ตาราง ER1 บน Neon Postgres: 21 ตาราง source + 4 ตาราง derived (Fact_Inventory_Snapshot, Fact_Stock_Movement, Fact_Order_Platform_Fees, Fact_FIFO_Allocation) = 25 ตาราง |
| 2 | **Extract** | ER1 (Postgres) | ดึงข้อมูลเดือนนั้นออกเป็นไฟล์ | Data Lake โซน Raw: ไฟล์ Parquet บน Neon Object Storage |
| 3 | **Transform** | Raw Parquet | มาตรฐานข้อมูล (ชนิด/วันที่/คีย์) + **Data Quality checks** | Lake โซน Standardize + รายงาน DQ (ผ่าน/ไม่ผ่าน ต่อกฎ) |
| 4 | **Load** | Standardize Parquet | โหลดเข้า Warehouse (DuckDB, ER2 star schema) + สร้าง Mart | ER2: Fact_Sales/Dim ... + Mart รายเดือน/Product Group |
| 5 | **Validate** | ER1 vs ER2 | Reconcile (จำนวนแถว/ยอดรวมต้องตรงกัน) | หลักฐาน Validate → ถ้าผ่านจึง **Publish Snapshot** เดือนนั้นให้ Dashboard เห็น |

จุดเด่นให้โชว์สด: **มีนาคมมี SKU ไม่ถูกต้อง** → DQ block → Review & Fix → Revalidate → Resume (เห็น error handling ครบ)

## 1.5 ขอบเขตสมมุติฐานของโมเดลกำไร (พูดตอนนำเสนอ)

> โมเดลนี้ไม่รวมค่าใช้จ่ายคงที่ (เงินเดือน ค่าเช่า) และภาษี เพราะวิชานี้เน้นการออกแบบระบบข้อมูล ไม่ใช่การบัญชี

- **อัตรากำไร (Profit Margin)** = กำไรหลังหักต้นทุนสินค้า ค่าธรรมเนียมแพลตฟอร์ม ค่าจัดส่ง affiliate Ads ของแจกฟรี และ claim ÷ ยอดขายอ้างอิง (Gross Reference Sales) เกณฑ์ ≥ 10%
- **ไม่ใช่ Gross Margin** ตามตำรา (ซึ่งหักแค่ COGS และจะได้ราว 60%) — ถ้าอาจารย์ถาม ให้ตอบตามนี้
- ตัวหารเป็น Gross ไม่ใช่ยอดขายสุทธิ จึงต้องบอกเสมอว่า "ต่อ Gross"
- **สัดส่วนต้นทุนการตลาดต่อ Gross (Marketing Cost Ratio)** = (Campaign + Voucher + Affiliate + Ads + Free Sample) ÷ Gross เกณฑ์ ≤ 30%
- หมายเหตุ: บนหน้าจอปัจจุบันยังใช้ชื่อเดิม "อัตราคุ้มครองกำไร (Profit Protection)" และ "Marketing GAP" (ยังไม่ได้ deploy ชื่อใหม่) — ตอนพูดให้ใช้ชื่อใหม่และชี้ว่าคือการ์ดใบเดียวกัน

## 2. ทำไม Forecast ต้องรอ 5 เดือน (ตอบตามโค้ดจริง)

- ระบบทำนาย **Net Revenue เดือนถัดไป แยก Product Group PG01–PG05**
- การประเมินความแม่นใช้ **walk-forward**: ย้อนทำนายเดือน 2, 3, 4… ด้วยข้อมูลเท่าที่ "รู้ในตอนนั้น" แล้วเทียบกับของจริง → ต้องมีประวัติพอให้ได้จุดเทียบหลายจุด
- Baseline ต้องมีอย่างน้อย 3 เดือนย้อนหลังเพื่อเฉลี่ย; ครบ 5 เดือน = ประเมิน Baseline ได้ ~4 จุด
- ML (Ridge) ต้องมีข้อมูลฝึก ≥ 2 เดือน และ **≥ 3 origins** → ต้องมีข้อมูล ≥ **6 เดือน** จึงจะ "มีสิทธิ์" เป็น challenger
- ดังนั้น 5 เดือน = เกณฑ์ขั้นต่ำของ Demo ให้เริ่ม Official Forecast (ใช้ Baseline) และเมื่อประวัติครบ ≥ 6 เดือน ML จึงเริ่มถูกเทียบได้
- **ตอบอาจารย์:** "ไม่ใช่ตัวเลขวิเศษ แต่เป็นขั้นต่ำเพื่อให้การวัดความแม่นมีหลายจุด ไม่ใช่เดาจากเดือนเดียว" (ปุ่ม/ตัวเลขนี้เป็น policy ของ Demo — พูดตรง ๆ ได้)

## 3. Forecast → Plan → Actual → เทียบความแม่น

1. Publish ครบ ≥5 เดือน → **Generate Forecast** เดือนถัดไป → **Seal** (ล็อก แก้ไม่ได้ ป้องกันย้อนปรับให้แม่น)
2. **เลือกแผน** (Ads / Campaign / Voucher) → บันทึก (ต้องบันทึกก่อนนำเข้าเดือนนั้น และต้องมี Official Forecast ที่ Seal แล้ว)
3. นำเข้า **Actual** เดือนนั้นผ่าน pipeline 5 ขั้น → Publish
4. **ประเมิน:** เทียบ Forecast vs Actual (ไม่ขึ้นกับแผน) และเทียบ "แผน vs ผลจริง" แยกต่างหาก (แผนคือเป้า/งบ ส่วน Forecast คือการคาดการณ์ฐาน — Dashboard ระบุว่า execution not verified)

**Baseline คิดจาก:** เลือกตัวที่ WAPE ต่ำกว่าระหว่าง
- naive = ยอดเดือนก่อนหน้า
- trailing-3-month mean = ค่าเฉลี่ย 3 เดือนล่าสุด (แยกต่อกลุ่ม)

**ML คิดจาก:** Ridge regression (pooled ทั้ง 5 กลุ่ม) features = lag1 (ยอดเดือนก่อน), ค่าเฉลี่ย 3 เดือน, จำนวนวันในเดือนเป้าหมาย, one-hot กลุ่มสินค้า; ฝึกด้วย expanding window; ห้ามใช้ข้อมูลหลังวันตัด (ถ้ามี → error `FORECAST_LEAKAGE`)

**ตัวชี้วัด:** WAPE = Σ|ผิดพลาด| ÷ Σ จริง (หลัก), MAE, Bias (Forecast − Actual)

**เมื่อไหร่ "สวิตช์":** ไม่สวิตช์อัตโนมัติ — ML ทำเป็น Shadow (บันทึกก่อนรู้ Actual) แล้ว Champion–Challenger monitor แนะนำ `RECOMMEND_REVIEW` เมื่อ มีข้อมูล ≥6 เดือน, WAPE ML ดีกว่า ≥2 pp, ชนะ ≥4 จาก 6 เดือน, ไม่มีกลุ่มแย่กว่าเกิน 5 pp → คนตัดสินใจเอง (ตรงกับ MLOps Ch.7: validate vs baseline + monitoring)

## 3.5 สถาปัตยกรรมที่ใช้ (พูดชื่อให้ตรงกับสไลด์อาจารย์)

**ภาพรวม:** *End-to-end advanced analytics platform* แบบ **Database → Data Lake → Data Warehouse → Dashboard/ML** (Ch.1 และ Ch.8 "Database–Data lake–Data Warehouse")

```
Source CSV(ZIP) ─► ER1 OLTP ─► Lake: landing → raw → standardized ─► ER2 Warehouse ─► Dashboard
                  (Postgres)    (Parquet, Neon Object Storage)        (DuckDB star)      + ML/Forecast
                         └── control/governance: checkpoint, DQ report, quarantine, lineage ──┘
```

| ชั้น | สถาปัตยกรรม/รูปแบบ | อ้างอิง |
|---|---|---|
| ER1 | OLTP, relational, normalized (PK/FK, bridge table) | Ch.2–3 |
| Data Lake | **Zone-based architecture**: landing (รับดิบ+hash) → raw (เก็บถาวร ไม่แก้) → standardized (ผ่านมาตรฐาน/DQ = "trusted") + โซน governance/control; เก็บเป็น **Parquet** (open format) บน object storage | Ch.4 Zone-Based / Multi-zone |
| Data Warehouse | **Kimball dimensional model**: star schema (Fact + Dim + conformed Dim_Date) และ **Data Mart** (Mart_Product_Group_Daily_Performance) + View KPI | Ch.5 |
| Pipeline | **Batch + Incremental load** รายเดือน (เลือกเฉพาะแถวที่เปลี่ยนด้วย change keys), แยก 5 stage แบบ modular, checkpoint, idempotent upsert | Ch.6 |
| ETL/ELT | แบบผสม: ER1→Lake เป็น Extract-Load (เก็บดิบก่อน) แล้ว Transform ใน Lake แล้วจึง Load เข้า Warehouse | Ch.6 ETL vs ELT |
| ML | Forecast + Baseline เทียบ ML (walk-forward), **Shadow ML**, **Champion–Challenger**, Feature Store แบบ point-in-time, คนอนุมัติเอง ≈ **MLOps level 0–1** (pipeline เป็นสคริปต์ มี monitoring แต่ยังไม่ retrain อัตโนมัติ) | Ch.7 |
| การรันจริง | Dashboard เป็นเว็บ (Vercel) → API → แต่ละ stage รันบน GitHub Actions/Python worker, ฐานข้อมูล Neon Postgres, Warehouse ด้วย DuckDB | Ch.1 |

**หลักการออกแบบ (design principles)**
1. **Separation of concerns / single responsibility:** 1 stage = 1 หน้าที่ ต่อกันผ่านไฟล์ Parquet (Ch.6 Modular design)
2. **Schema-as-contract:** schema ER1 (DBML) เป็นที่มาของกฎ DQ 92 ข้อและโครงตารางทั้งหมด
3. **Immutable raw + lineage:** เก็บดิบพร้อม SHA-256 ไม่แก้; แก้ข้อมูลผิดเป็น "overlay" แยก ไม่แก้ต้นฉบับ; ตามรอยย้อนถึงไฟล์ต้นทางได้ (Ch.6 data lineage)
4. **Defense in depth DQ:** ตรวจ 2 ด่าน (ก่อนเข้า ER1 และก่อนเข้า Standardized) + Reconcile ปลายทาง (Ch.6 ETL testing: source-to-target)
5. **Fail-closed:** ไม่ผ่านไม่ Publish; ล้มแล้ว Rollback/Resume ได้ (Ch.6 error handling, checkpoint, idempotency)
6. **Point-in-time / no leakage:** Forecast ใช้เฉพาะข้อมูลที่ Publish แล้ว, Seal แล้วแก้ไม่ได้ (Ch.7)
7. **Human-in-the-loop:** ML เป็นผู้ช่วยแนะนำ ไม่เปลี่ยนโมเดลหลักเอง

**ข้อจำกัดที่ควรยอมรับตรง ๆ** (กันอาจารย์ซัก)
- Lake เป็น Parquet ธรรมดา **ยังไม่ใช่ Lakehouse เต็มรูปแบบ** (ไม่มี table format แบบ Delta/Iceberg ที่ให้ ACID/versioning เอง; ความถูกต้องมาจาก transaction ของ ER1/ER2 + checkpoint + hash)
- ประมวลผลเป็น **Batch รายเดือน** ไม่ใช่ real-time/streaming (ไม่ใช่ Lambda/Kappa)
- ไม่ใช่ Data Pond/Inmon: Warehouse เป็นแบบ Kimball ไม่ได้มี Enterprise DW แบบ 3NF ตรงกลาง
- MLOps ยังไม่มี Continuous Training; แหล่งข้อมูลเป็น CSV แบบจำลอง

## 4. หลักออกแบบ → อ้างสไลด์อาจารย์

| สิ่งที่ระบบทำ | หลักการ / บท |
|---|---|
| 21 ตาราง Master (Dim/Ref) vs Transaction (Fact) ต้นทางแยกชัด; ราคา ณ ตอนขายเก็บใน order item (Base_Unit_Price_At_Sale) | Ch.3 Master vs Transaction (เก็บราคา ณ เวลาขายแยกจาก master) |
| ER1 normalized (key/FK, bridge table many-to-many) | Ch.2 Normalization |
| Lake แยกโซน Raw → Standardize (Parquet, write-once) | Ch.4 Data Lake zone design (ไม่ใช่ mono-zone) |
| ER2 star schema: Fact (ยอดขาย) + Dim (Product/Creator/Voucher/Date) + Mart | Ch.5 Dimensional/Kimball, Facts & Dimensions |
| Extract→Transform→Load แยก stage = single responsibility; Incremental รายเดือน; DQ validation; Reconcile ER1↔ER2 (source-to-target test); block→fix→resume; idempotent/กันรันซ้ำ; log/evidence ทุก stage | Ch.6 ETL: modular, incremental, error handling, ETL testing |
| Walk-forward vs baseline, Shadow ML, Feature Store point-in-time, Champion–Challenger, monitoring, human approval | Ch.7 MLOps (model validation > baseline, monitoring, feature store) |

มคอ.3 rubric 6 ด้าน ×10: Data Sources (21 ตาราง+ZIP+hash) · Database/Lake/Warehouse (ER1/Lake/ER2) · ETL (5 stage+DQ) · Dashboard (≥2 บทบาท) · AI/ML (Forecast+Monitor) · Business Story (เสื้อผ้า TikTok Shop: ตัดสินใจงบ Ads/คูปอง)

**ข้อควรระวัง (พูดตรง ๆ จะได้คะแนนความน่าเชื่อถือ):** ข้อมูลเป็น synthetic เพื่อการเรียน; Source เป็น CSV จาก ZIP (ถ้าอาจารย์ถามว่า "diverse sources" ให้ตอบว่า 21 ตารางจากหลายระบบธุรกิจ: orders, inventory/receipt, marketing, claims, reference rules — และยอมรับว่าไม่มี unstructured/external API)

## 5. โครงการนำเสนอแบบ Consulting (ประมาณ 15–20 นาที)

1. **ปัญหาธุรกิจ (2 นาที):** ร้านแฟชั่นบน TikTok Shop ต้องตัดสินใจงบ Ads/คูปองล่วงหน้า แต่ไม่รู้ยอดเดือนหน้า → ต้องการข้อมูลเชื่อถือได้ + พยากรณ์ที่ตรวจสอบได้
2. **สถาปัตยกรรม (3 นาที):** วาด Source → ER1 (Postgres) → Lake (Raw/Standardize) → ER2 (DuckDB star) → Dashboard/ML
3. **Live Demo (8 นาที):** (ก) รันเดือนแรกผ่าน 5 ขั้นดูผลแต่ละขั้น (ข) มีนาคม DQ block → fix → resume (ค) Data Operations Overview (ง) Dashboard ผู้บริหาร + ปฏิบัติการ
4. **ML (3 นาที):** Forecast Seal → เลือกแผน → Actual → WAPE เทียบ Baseline; ML เป็น Shadow ยังไม่แทนที่
5. **สรุป/ข้อจำกัด (2 นาที):** ข้อมูลสังเคราะห์, ML แนะนำเท่านั้น, ต่อยอด

**เสาร์:** หลัง Lab clear ข้อมูล ER1 จะถูกลบจริง (ไม่ใช่แค่ซ่อน) และเริ่มใหม่จากเดือนแรก — รันเดือนที่ต้องโชว์ (เดือนแรก + มีนาคม) สดได้ ส่วนเดือนอื่นอย่ารันทั้งหมดสด เพราะต้อง Publish ≥5 เดือนก่อน Forecast → **ซ้อมวันศุกร์ทั้งชุด + เตรียม screenshot สำรอง**

## 6. ถาม–ตอบ: คำถามที่อาจารย์น่าจะถาม (ตอบได้ทันที)

**ก. สถาปัตยกรรมและการออกแบบ**

**Q1. ทำไมต้องแยก ER1 / Lake / ER2 ทำไมไม่เก็บที่เดียว?**
A: ทำหน้าที่ต่างกัน — ER1 (OLTP) เก็บธุรกรรมแบบ normalize ให้ข้อมูลถูกต้อง, Lake เก็บข้อมูลดิบ/มาตรฐานเป็น Parquet ไว้ย้อนตรวจสอบและทำ ML, ER2 (star schema) จัดโครงให้วิเคราะห์/ทำ Dashboard เร็วและเข้าใจง่าย (Ch.1, Ch.8)

**Q2. ทำไม ER1 มี 25 ตาราง แต่ ER2 เหลือ 11?**
A: Warehouse เก็บเฉพาะสิ่งที่ใช้วิเคราะห์ตามหลัก dimensional (Ch.5): รวมหลายตารางธุรกรรมเป็น Fact ระดับ Order Item, ตาราง reference/ต้นทุนถูกคำนวณรวมในแถว Fact, claim เข้า Mart เป็นยอดรายวัน

**Q3. ใช้ Data Lake แบบไหน ใช่ Lakehouse ไหม?**
A: Zone-based (landing → raw → standardized) เก็บ Parquet บน object storage — **ไม่ใช่ Lakehouse เต็มรูปแบบ** เพราะไม่มี Delta/Iceberg; ความถูกต้องมาจาก transaction ของ ER1/ER2 + checkpoint + hash

**Q4. Warehouse แบบ Kimball หรือ Inmon?**
A: Kimball — star schema + data mart; ไม่มี Enterprise DW แบบ 3NF ตรงกลาง (Ch.5)

**Q5. เป็น ETL หรือ ELT?**
A: ผสม — ER1→Lake เก็บดิบก่อน (E-L) แล้ว Transform ใน Lake แล้วโหลดเข้า Warehouse (Ch.6)

**Q6. ทำไมไม่ใช้ Streaming/Real-time?**
A: โจทย์ตัดสินใจงบ Ads/คูปองรายเดือน ข้อมูลธุรกิจอัปเดตเป็นรอบ จึงใช้ Batch รายเดือนที่ตรวจสอบได้ง่ายกว่า (ไม่จำเป็นต้อง Lambda/Kappa)

**ข. Pipeline และคุณภาพข้อมูล**

**Q7. ถ้าข้อมูลผิดจะเกิดอะไร?**
A: DQ ตรวจ 92 กฎก่อนเข้า ER1 และตรวจซ้ำก่อนเข้า Standardized ถ้าตก → หยุด ไม่เขียนอะไร → Review & Fix (แก้เป็น overlay ไม่แก้ไฟล์ต้นฉบับ) → Revalidate → Resume (ตัวอย่างสด: มีนาคม)

**Q8. รันซ้ำแล้วข้อมูลซ้ำไหม?**
A: ไม่ซ้ำ — ใช้ upsert ตาม business key + checkpoint (ขั้นที่สำเร็จแล้วไม่รันซ้ำ) = idempotent (Ch.6)

**Q9. รู้ได้ยังไงว่าข้อมูลใน Warehouse ถูกต้อง?**
A: ขั้น Validate เทียบ ER1 กับ ER2 21 ข้อ (จำนวนแถว, Net Revenue, สูตรทุกแถว, Fact→Mart, profit protection) + สุ่มตาม lineage กลับถึงไฟล์ CSV; ไม่ผ่านไม่ Publish

**Q10. ทำไมโหลดเป็นรายเดือนแบบ incremental?**
A: โหลดเฉพาะแถวที่เปลี่ยน (change keys) ลดงานและกันซ้ำ (Ch.6 incremental load) ข้อจำกัด: ไม่รองรับ refund หลังจ่ายแล้ว (`T03`) ใน Demo นี้

**ค. Forecast / ML**

**Q11. ทำไมต้องรอ 5 เดือนถึงจะ Forecast ได้?**
A: เป็นเกณฑ์ขั้นต่ำของ Demo เพื่อให้วัดความแม่นแบบ walk-forward ได้หลายจุดไม่ใช่เดาจากเดือนเดียว; ML ต้อง ≥3 origins จึงต้อง ≥6 เดือนถึงจะมีสิทธิ์เป็น challenger

**Q12. Baseline กับ ML คิดต่างกันอย่างไร?**
A: Baseline = เลือกดีกว่าระหว่างยอดเดือนก่อน กับค่าเฉลี่ย 3 เดือน (ต่อกลุ่มสินค้า); ML = Ridge regression ใช้ lag1, ค่าเฉลี่ย 3 เดือน, จำนวนวัน, กลุ่มสินค้า

**Q13. วัดความแม่นด้วยอะไร?**
A: WAPE เป็นหลัก (Σ|ผิด| ÷ Σ จริง) ควบคู่ MAE และ Bias; เทียบบน origins เดียวกัน

**Q14. เมื่อไหร่สลับไปใช้ ML?**
A: ไม่สลับอัตโนมัติ — ระบบแนะนำ "ควรทบทวน" เมื่อข้อมูล ≥6 เดือน, WAPE ดีกว่า ≥2 pp, ชนะ ≥4 จาก 6 เดือน, ไม่มีกลุ่มแย่กว่าเกิน 5 pp แล้วคนตัดสินใจเอง (Ch.7: validate vs baseline + monitoring)

**Q15. ป้องกัน data leakage อย่างไร?**
A: ใช้เฉพาะข้อมูลที่ Publish ถึงเดือนตัด (ถ้ามีข้อมูลเกินวันตัด → error), Seal Forecast แก้ไม่ได้, Feature Store บันทึกแบบ point-in-time, ห้ามใช้ feature ที่เป็นแผน/คำตอบ

**Q16. แผน Ads/คูปองที่เลือกมีผลต่อ Forecast หรือ Actual ไหม?**
A: ไม่ — Forecast และ Actual ไม่ขึ้นกับแผน; แผนบันทึกไว้เทียบเป็นเป้า/งบ และระบบระบุว่า "ยังไม่ยืนยันว่าทำตามแผนจริง" (ไม่มีข้อมูล execution)

**ง. ความจริงและข้อจำกัด**

**Q17. ข้อมูลเป็นของจริงไหม?**
A: เป็นข้อมูลจำลองเพื่อการเรียน (ระบุในระบบว่า SYNTHETIC_EDUCATIONAL) ออกแบบให้มีกรณีผิดพลาดตั้งใจ (เช่น มีนาคม)

**Q18. ข้อมูลหลากหลายพอไหม (rubric ต้องการ 3–4 แหล่ง)?**
A: 21 ตารางจากหลายระบบธุรกิจ (ออเดอร์, คลัง/รับสินค้า, marketing/ads, claims, กฎอ้างอิง/เป้าหมาย) แต่เป็น CSV ทั้งหมด ไม่มี unstructured/external API — ยอมรับตรง ๆ และเสนอเป็นงานต่อยอด

**Q19. ระบบนี้ production-ready ไหม?**
A: ไม่ — เป็น Demo เชิงวิชาการ: ไม่มี login/approval workflow, MLOps ยังไม่มี retrain อัตโนมัติ

**Q20. ถ้าจะต่อยอดทำอะไร?**
A: เพิ่มแหล่งข้อมูลจริง/ภายนอก (API, รีวิวข้อความ), table format แบบ Delta/Iceberg, retrain อัตโนมัติ, ระบบสิทธิ์ตามบทบาท
