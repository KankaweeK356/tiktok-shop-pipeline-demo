# TikTok Shop Data Pipeline Demo — Implementation Blueprint

## วัตถุประสงค์
- ทดลอง End-to-End: Synthetic CSV -> SQLite Business ER1 V3 -> Landing/Raw/Standardized Parquet Lake -> DuckDB Kimball ER2 V5 -> KPI/what-if
- **ยึด ER1 V3 25 ตาราง, ER2 V5 6 Dimensions + 4 Facts + 1 Mart + 1 SQL View** ไม่เพิ่มตารางธุรกิจ
- ข้อมูลทั้งหมดเป็น **MOCK** เพื่อการศึกษา ไม่ใช่ข้อมูล TikTok/API จริง ค่าธรรมเนียมแพลตฟอร์ม 10% เป็นสมมติฐาน

## แหล่งเก็บ / ที่รัน / ผลลัพธ์
| บทบาท | สถานที่ | รายละเอียด |
| --- | --- | --- |
| เก็บ Source + Code + DBML | GitHub repository / ไฟล์ ZIP | versioned files; ไม่เก็บ output runtime เป็น source of truth |
| รัน Python Modules | Google Colab | 6 Sections; รันได้ตามลำดับหรือ Resume stage ที่พัง |
| ER1 Business DB | `/content/.../output/main/er1.sqlite` | 25 physical tables |
| Data Lake | `output/main/lake/landing|raw|standardized|control` | Parquet + CSV landing + manifest/checkpoint/log |
| ER2 Warehouse | `output/main/er2.duckdb` | 11 physical tables + 1 logical view |
| แสดงผล | cells ใน Colab | Functional/Lineage/Error/Performance/Business summary |
| เก็บถาวร (ทางเลือก) | Google Drive | ส่งออกไฟล์ output ที่รันเสร็จจาก Colab; ต้องเลือกทำเอง |

## ลำดับประมวลผลในแต่ละ Batch
0. Source ของ Batch — `source/initial` หรือ `source/incremental` (แยกไฟล์)
1. `ingest`: Upsert master/transactions to ER1, derive locked campaign price, voucher eligibility/cap/allocation, affiliate payout, FIFO-based COGS, stock snapshots; full SQLite transaction
2. `extract`: เก็บสำเนา CSV ลง Landing และส่งออก ER1 25 ตารางเป็น **Raw snapshot** Parquet พร้อม checksum manifest
3. `transform`: อ่าน Raw, ตรวจ campaign overlap/discount, สร้าง standardized ER2 dimensions และ **changed transaction rows** โดยใช้ changed-keys จาก Ingest; generate dirty Date×ProductGroup keys และ claim rollup ภายนอก ER2
4. `load`: upsert Dimensions + เฉพาะ affected Facts ใน DuckDB, rebuild Mart เฉพาะ dirty keys, update logical Monthly KPI SQL View ภายใน transaction เดียว
5. `validate`: reconcile ER1/ER2/Mart, บันทึก functional + lineage report

**ข้อจำกัด Incremental ที่ต้องบอกอาจารย์:** Batch 2 ใช้ `full reference Raw snapshots` ใน Lake เพื่อทำ lookup แต่ **ไม่ reload all Sales Facts**; ใช้ changed keys Upsert Fact และคำนวณ Mart เฉพาะ affected days. นี่คือ incremental warehouse processing ไม่ใช่ full CDC extraction จาก TikTok.

## Run 1 / Run 2 (deterministic)
- Random seed 7202; Initial = October 2026 จำนวน **800 Orders**, 5 Product Groups, 140 SKUs; Pending/Cancelled ไม่นับรายได้
- Incremental = 1 Nov 2026 จำนวน **100 Orders ใหม่**, **24 Order จาก Oct Pending -> Nov Paid**, **8 simulated fulfillment adjustments ของ Oct Paid Orders**; มี Ads และ Free Sample เพิ่ม
- Run 2 source batch เดิมอีกครั้ง -> checkpointer SKIPS processed batch; มูลค่าของ Warehouse ต้องเหมือนเดิม (idempotent)
- Reset เฉพาะเมื่อผู้ใช้เลือก: ลบ output workspace เพื่อเริ่ม Run 1 ใหม่ ผลธุรกิจเหมือนเดิมเมื่อ seed+schema+source เดิม
- Data generator ภายใน repo ทำซ้ำได้; `source/` รวม CSV แล้วเพื่อเริ่ม demo ได้เลย

## Validation / Lineage
- Validation: PK/FK; vouchers per order reconcile; paid revenue; sale/gross/COGS/affiliate ER1 vs ER2; Ads/Sample/Claim to Mart; no fanout; price/fee/Profit Protection
- Lineage: `Order_Item_ID` ตรง Source, ER1, Raw/Standardized filenames, ER2 item, corresponding Date×PG Mart, and month KPI; KPIs are *aggregates*, not 1:1 to an item
- Controls: `checkpoint_{batch}.json`, `changes_{batch}.json`, `stage_history.jsonl`, `manifest_{batch}.json`, `allocation_audit_{batch}.json`, and CSV reports.

## Error Recovery Test — test area แยกจาก Main
| Case | จุดพัง | Inject | Recovery |
|---|---|---|---|
| E01 | Ingest | unknown SKU FK | แก้ CSV แล้ว Retry from Ingest |
| E02 | Ingest | missing source Orders CSV | คืนไฟล์ แล้ว Retry from Ingest |
| T01 | Transform | voucher allocated > eligible Sales | กู้ค่าข้อมูลปกติ แล้ว Retry from Transform |
| T02 | Transform | conflicting campaign intervals | คืน Master Rules แล้ว Retry from Transform |
| L01 | Load | fail after loading Sales, before commit | rollback entire DuckDB load, retry from Load |
| L02 | Incremental | replay same batch | no duplicate, checkpoint skip (expected SUCCESS, not ERROR) |

Specific Error เป็น Demo สดหลัก; `all` mode ทดสอบทั้งหมดอัตโนมัติ; `random` mode ที่กำหนด seed เลือก 1 case ได้เหมือนเดิมเมื่อ rerun. **ไม่สุ่ม Inject Error ใน Normal Run.**

## Performance
- Test end-to-end ตามจำนวน Initial Orders (default 100/300/800) บน workspace แยก พร้อมบันทึก latency, paid-item throughput, stage times, functional passes
- สูตร `Latency = end_time - start_time`; `Throughput = count(paid Sales Order Items)/seconds` ระบุ denominator สม่ำเสมอ
- ถ้าต้องการ Stress Test ใหญ่ ตั้ง `sizes=(1000, 4000, 12000)` ใน Colab; Runtime/CPU อาจเปลี่ยน จึงต้องรายงาน machine configuration และเวลาเครื่องนั้นจริง

## KPI / Business Rules
- Net Revenue = หลัง Campaign + seller voucher, ค่าจัดส่งที่ลูกค้าจ่ายไม่นับใน Net Product Revenue
- COGS = 40% x Base price; Platform Fee = 10% x Net Revenue; Affiliate = product-group rate x item net
- Profit = Net Revenue - COGS - Platform - Fulfillment - Affiliate - Ads - Sample - Claim (no double discounts)
- Profit Protection Required = 10% x Gross Reference Sales (full price); Actual Profit Margin = Profit / Net Revenue แยก
- Scenario: commission ceiling *on current affiliate-eligible sales* with existing demand and other costs fixed; NOT demand-optimal recommendation.

## ข้อจำกัดสำคัญ
- ER1 สมมติ FIFO ตามโครงสร้างเดิมและมีต้นทุนต่อ Group คงที่ทุก Lot ไม่ได้พัฒนาระบบคลังจริง
- `Fact_Order_Platform_Fees` อาจว่าง เพราะ Demo ใช้ Ref Platform Fee Estimate เท่านั้น ไม่แต่งข้อมูล Fee จริง
- หาก Fulfillment ไม่พร้อม ให้ Fact Cost_Basis UNKNOWN และ Mart Profit เป็น NULL จนกว่าจะครบ ไม่อ้างเป็นกำไรสมบูรณ์
- Source files / Report prices and fees are synthetic; no claims of TikTok policy/market performance
- SQLite/Parquet/DuckDB ใน Colab Runtime เป็นไฟล์ชั่วคราว; หากต้อง Resume ข้าม Runtime ต้องบันทึก Workspace ไป Drive และคืนกลับด้วยไฟล์ทั้งหมด
