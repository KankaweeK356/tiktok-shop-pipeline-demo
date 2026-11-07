# TikTok Shop — Data Pipeline Demo

**จากข้อมูลขายจำลอง ไปสู่รายงานยอดขายและกำไรที่ตรวจสอบที่มาได้**

โปรเจกต์นี้สาธิตการทำ Data Pipeline ตั้งแต่รับข้อมูลธุรกิจ สร้างฐานข้อมูล จัดเก็บใน Data Lake ไปจนถึง Data Warehouse พร้อมทดสอบการรับข้อมูลรอบใหม่ การตรวจยอด และการกู้คืนเมื่อเกิดข้อผิดพลาด

**เส้นทางข้อมูล:** `Mock CSV → SQLite (ER 1 V3) → Parquet Data Lake → DuckDB (ER 2 V5) → KPI`

> **ข้อมูลทั้งหมดเป็นข้อมูลจำลองเพื่อการศึกษา** ไม่ได้เชื่อมต่อ TikTok Shop API ไม่ใช่ข้อมูลลูกค้าหรือยอดขายจริง และ Platform Fee 10% เป็นสมมติฐานของกรณีศึกษา

## เริ่มทดลองด้วย Google Colab

ไม่ต้องติดตั้ง Database หรือ Python บนคอมพิวเตอร์ของตัวเอง ใช้ Google Colab เป็นหน้าจอรันทุกขั้นตอน

1. เปิด [`notebooks/TikTok_Shop_Demo.ipynb`](notebooks/TikTok_Shop_Demo.ipynb) แล้วเลือกเปิดด้วย **Google Colab** หรือเปิด [Google Colab](https://colab.research.google.com/) แล้วเลือกไฟล์จากแท็บ **GitHub**
2. ในหัวข้อ **00 เตรียมโปรเจกต์** ใส่ลิงก์ Repository นี้ในช่อง `REPO_URL` (เช่น `https://github.com/USERNAME/tiktok-shop-pipeline-demo`) แล้วรัน Cell
3. รันหัวข้อ **01 Run 1** ต่อด้วย **02 Run 2** เพื่อเห็นข้อมูลตั้งต้นและข้อมูลที่เพิ่มเข้ามา
4. รันหัวข้อ **03–05** เพื่อดูผลตรวจข้อมูล ทดลอง Error และดูผลประสิทธิภาพกับกำไร

**เริ่ม Demo ใหม่:** ที่หัวข้อ 00 ตั้ง `RESET_DEMO=True` แล้วรัน 1 ครั้ง ก่อนเปลี่ยนกลับเป็น `False` จากนั้นเริ่ม Run 1 ใหม่  
**ลอง Run 2 ซ้ำ:** รันหัวข้อ 02 อีกครั้ง จำนวนรายการและยอดขายต้องไม่เพิ่มจาก Batch เดิม

หากเพิ่งเริ่มใช้ GitHub อ่าน [คู่มือสร้าง Repository และอัปโหลดไฟล์](docs/GITHUB_SETUP_TH.md) หรืออ่าน [วิธีเริ่ม Demo แบบสั้น](docs/QUICK_START_TH.md)

## แต่ละขั้นทำอะไร และเห็นผลตรงไหน?

| ขั้นตอนใน Colab | ทำอะไร | สิ่งที่เห็นใต้ Cell |
|---|---|---|
| **00 เตรียมโปรเจกต์** | โหลด Code และ CSV จาก GitHub | ตำแหน่งไฟล์และจำนวนข้อมูลตั้งต้น |
| **01 Run 1 — ข้อมูลตั้งต้น** | นำข้อมูลเดือนตุลาคมผ่าน Database, Lake และ Warehouse | จำนวนรายการ ยอดขาย และผลตรวจยอด |
| **02 Run 2 — ข้อมูลใหม่** | เพิ่ม Order ใหม่ เปลี่ยนสถานะ Order และปรับต้นทุนที่เข้าทีหลัง | เปรียบเทียบก่อน/หลัง และผลรันซ้ำ |
| **03 ตรวจยอดและที่มาข้อมูล** | ตรวจยอดระหว่าง ER 1 กับ ER 2 และติดตาม Order ตัวอย่าง | PASS/FAIL และเส้นทางของข้อมูล |
| **04 ทดลอง Error และการกู้คืน** | จำลองข้อผิดพลาด แก้สาเหตุ แล้วรันใหม่จากขั้นที่เหมาะสม | Error ที่พบ จุดเริ่ม Retry และผลหลังแก้ |
| **05 ประสิทธิภาพและผลธุรกิจ** | จับเวลาการประมวลผลและคำนวณกำไร | Latency, Throughput, KPI และ Affiliate Scenario |

**Run 1 / Run 2 ไม่ได้หมายถึงรันได้แค่สองครั้ง:** Run 1 ใช้สร้างข้อมูลตั้งต้นหลัง Reset ส่วน Run 2 เป็นการรับข้อมูลใหม่ (Incremental) ที่สามารถทำซ้ำได้โดยไม่เพิ่มยอดซ้ำ

## ผลลัพธ์ถูกเก็บไว้ที่ไหน?

Code ทั้งหมดทำงานใน **Google Colab** และสร้างไฟล์ผลลัพธ์ในพื้นที่ของ Colab ระหว่างรัน ไม่ได้บันทึก Database ลง GitHub อัตโนมัติ

| ไฟล์/โฟลเดอร์ที่สร้าง | เก็บอะไร |
|---|---|
| `output/main/er1.sqlite` | Business Database ตาม ER 1 V3 (25 ตาราง) |
| `output/main/lake/` | Landing, Raw, Standardized และ Control ของ Data Lake |
| `output/main/er2.duckdb` | Warehouse ตาม ER 2 V5: 6 Dimensions, 4 Facts, 1 Mart และ 1 KPI View |
| `output/main/reports/` | รายงานตรวจยอด ที่มาข้อมูล และผลธุรกิจ |
| `output/test/` | ผลทดสอบ Error แยกจากข้อมูลหลัก |
| `output/performance/` | รายงานเวลาประมวลผลและจำนวนรายการต่อวินาที |

ดูผลสรุปได้ **ใต้ Code Cell ใน Colab** และเปิดไฟล์ที่สร้างจากแถบ **Files** ด้านซ้าย หากปิดหรือ Reset Colab Runtime ไฟล์ในพื้นที่ชั่วคราวอาจหาย สามารถรันสร้างใหม่ได้ หรือดาวน์โหลด/คัดลอกไป Google Drive เพื่อเก็บต่อ

## โครงสร้าง Repository

```text
README.md             เริ่มอ่านที่นี่
notebooks/            Google Colab สำหรับสาธิต
source/               CSV จำลองสำหรับ Run 1 และ Run 2
schemas/              ER 1 V3 และ ER 2 V5 (DBML)
pipeline/             Python Modules สำหรับแต่ละขั้น
tests/                Automated Tests
sql/                  SQL ของ Monthly KPI View
docs/                 คู่มือ Mapping และหลักฐานการทดสอบ
requirements.txt      Python Libraries ที่ต้องใช้
```

## เราตรวจอะไรระหว่างการสาธิต?

- **ความถูกต้อง:** ยอดขาย ต้นทุน ส่วนลด และจำนวนรายการตรงกันระหว่าง ER 1, ER 2 และ Mart
- **ที่มาของข้อมูล:** ตาม `Order_Item_ID` จาก Source ไปถึง Sales Fact แล้วแสดงว่ารวมเข้าสู่ KPI วัน/เดือนใด
- **การรันซ้ำ:** รัน Incremental Batch เดิมแล้วไม่เกิดยอดขายหรือ Order Item เพิ่มซ้ำ
- **ความผิดพลาด:** ทดสอบกรณี Source ผิด, Transform ผิด และ Load ล้มเหลว พร้อม Recovery
- **ประสิทธิภาพ:** วัดระยะเวลาประมวลผลและ Throughput จากการรันจริงในสภาพแวดล้อมนั้น
- **ผลธุรกิจ:** รายงาน Net Revenue, Contribution Profit และเกณฑ์กำไรขั้นต่ำ 10% ของยอดขายตามราคาเต็ม

ตัวอย่างข้อมูลที่เตรียมไว้: **5 Product Groups, 140 SKUs, 800 Orders ตั้งต้น และ 100 Orders ใหม่ใน Run 2** พร้อมกรณี Order เดิมเพิ่งชำระเงินและต้นทุนเข้าทีหลัง ทั้งหมดสร้างขึ้นเพื่อทดสอบ Pipeline ไม่ใช่ข้อมูลจริง

## สถานะการทดสอบและข้อจำกัด

มีการตรวจ Schema, ทดสอบ SQLite และทดสอบ Logic ของ Pipeline/Recovery ในสภาพแวดล้อมพัฒนาแล้ว แต่ **ยังไม่ได้ยืนยันการรันครบเส้นทางด้วย DuckDB และ PyArrow จริงบน Google Colab** จึงควรรัน Notebook และเก็บผลทดสอบบน Colab ก่อนนำเสนอหรืออ้างว่า End-to-End ผ่านจริง

ดูขอบเขตการทดสอบและข้อจำกัดได้ที่ [VALIDATION_STATUS.md](docs/VALIDATION_STATUS.md) โดยตรง

## เอกสารประกอบ

- [คู่มือเริ่มต้นและรัน Colab](docs/QUICK_START_TH.md) — สำหรับคนที่อยากลองใช้งานทันที
- [คู่มือ GitHub สำหรับผู้เริ่มต้น](docs/GITHUB_SETUP_TH.md) — สำหรับเจ้าของ Repository
- [โครงสร้าง Pipeline และขอบเขตการทดสอบ](docs/IMPLEMENTATION_BLUEPRINT_TH.md) — สำหรับผู้ตรวจเชิงเทคนิค
- [Source-to-ER 1 Contract](docs/Source_to_ER1_Contract.csv) และ [ER 2 Mapping](docs/ER2_Source_to_Target_Mapping.csv) — สำหรับตรวจการแปลงข้อมูล
- [บทพูดนำเสนอ Demo](docs/DEMO_SCRIPT_FOR_TEACHER_TH.md) — สำหรับการสาธิตหน้าชั้น

