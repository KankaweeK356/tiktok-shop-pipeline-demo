# TikTok Shop — Data Pipeline Demo

**จากข้อมูลขายจำลอง ไปสู่รายงานยอดขายและกำไรที่ตรวจสอบที่มาได้**

โปรเจกต์นี้สาธิตการทำ Data Pipeline ตั้งแต่รับข้อมูลธุรกิจ สร้างฐานข้อมูล จัดเก็บใน Data Lake ไปจนถึง Data Warehouse พร้อมทดสอบการรับข้อมูลรอบใหม่ การตรวจยอด และการกู้คืนเมื่อเกิดข้อผิดพลาด

**เส้นทางข้อมูล:** `Mock CSV → SQLite (ER 1 V3) → Parquet Data Lake → DuckDB (ER 2 V5) → KPI`

> **ข้อมูลทั้งหมดเป็นข้อมูลจำลองเพื่อการศึกษา** ไม่ได้เชื่อมต่อ TikTok Shop API ไม่ใช่ข้อมูลลูกค้าหรือยอดขายจริง และ Platform Fee 10% เป็นสมมติฐานของกรณีศึกษา

## เปิด Demo บน Google Colab

[![เปิด Demo บน Google Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/main/notebooks/TikTok_Shop_Demo.ipynb)

**สำหรับผู้ทดลอง:** กดปุ่มด้านบน แล้วรันหัวข้อ 00 → 01 → 02 ต่อด้วย 03–05 ตามต้องการ

**ดูผลการทดสอบที่เผยแพร่แล้ว:** [reports/](reports/README.md) — เมื่อเจ้าของโปรเจกต์รัน Colab ผ่านครบและอัปโหลดรายงานที่ตรวจแล้ว

- **ไม่ต้องดาวน์โหลด ZIP หรืออัปโหลด Source เอง** — Notebook ดึง Code และข้อมูลจำลองจาก Repository นี้อัตโนมัติ
- **ไม่ต้องกรอก REPO_URL** — ตั้งลิงก์ Repository นี้ไว้ให้แล้ว
- ใช้บัญชี Google เพื่อเปิดและรัน Google Colab; ครั้งแรกอาจต้องกดเชื่อถือ Notebook และยืนยันการเชื่อมต่อ Runtime
- ส่วนที่ต้องติดตั้ง Python Libraries จะทำในหัวข้อ 00 ของ Notebook
- กด **Run 1** เพื่อสร้างข้อมูลตั้งต้น แล้วกด **Run 2** เพื่อเพิ่ม/อัปเดตข้อมูล
- รัน **Run 2** ซ้ำได้โดยไม่สร้างยอดขายซ้ำ และเลือกทดสอบ Error ในหัวข้อ 04 ได้

**ผลลัพธ์อยู่ที่ไหน:** แสดงสรุปใต้แต่ละ Cell ใน Colab ส่วนไฟล์ฐานข้อมูล, Data Lake และรายงานถูกสร้างใน `output/` บน Runtime ของแต่ละคน

**เริ่มใหม่:** ในหัวข้อ 00 ตั้ง `RESET_DEMO=True` แล้วรันหนึ่งครั้ง จากนั้นเปลี่ยนกลับเป็น `False` และรัน Run 1 ใหม่

อ่านรายละเอียดได้จาก [วิธีเริ่ม Demo แบบสั้น](docs/QUICK_START_TH.md) ส่วนผู้พัฒนาที่ต้องการแก้ไขไฟล์ อ่าน [คู่มือ GitHub](docs/GITHUB_SETUP_TH.md)

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

ดูผลสรุปได้ **ใต้ Code Cell ใน Colab** และเปิดไฟล์ที่สร้างจากแถบ **Files** ด้านซ้าย หากปิดหรือ Reset Colab Runtime ไฟล์ในพื้นที่ชั่วคราวอาจหาย สามารถรันสร้างใหม่ได้

### เก็บผลบน Google Drive (ไม่บังคับ)

ท้าย Notebook หัวข้อ **05.4** เลือก `DRIVE_ACTION=save` เพื่อบันทึก Snapshot ลง **Google Drive ของผู้รันเอง** ใน `MyDrive/TikTok_Shop_Demo/snapshots/` ระบบจะขอให้เชื่อม Drive เมื่อผู้ใช้เลือกเท่านั้น ข้อมูลบน GitHub ไม่เปลี่ยน และคนอื่นไม่เห็นผลบน Drive ของเรา

หากต้องการเคลียร์ Snapshot ให้เลือก `DRIVE_ACTION=clear` และพิมพ์ `CLEAR_TIKTOK_SHOP_DEMO` ในช่องยืนยัน ระบบลบ **เฉพาะ Snapshot ภายในโฟลเดอร์ Demo ที่ระบบจัดการ** ไม่ลบทั้ง Drive ไม่ลบไฟล์ใน GitHub และไม่ลบข้อมูลผลการรันใน Colab

### เผยแพร่รายงานผลทดสอบบน GitHub

1. รัน Run 1, Run 2, Functional/Lineage, Error Suite 6 กรณี, Performance และ Business Results บน Colab ให้ครบ
2. หัวข้อ **05.3** กดสร้าง `github_report_upload.zip` ระบบจะตรวจว่ารายงานทดสอบผ่านครบก่อนสร้างไฟล์
3. ดาวน์โหลด ZIP → แตกไฟล์ → อัปโหลดโฟลเดอร์ `reports/` กลับขึ้น GitHub และกด Commit changes
4. อาจารย์จะเปิด [reports/](reports/README.md) ดูผลสรุปที่ตรวจแล้วได้ โดยไม่ต้องรัน Colab เอง

**รายงานบน GitHub เป็น Snapshot ที่อัปโหลดด้วยตัวเอง ไม่ใช่ผลสดอัตโนมัติของทุกคนที่กดรัน**

## โครงสร้าง Repository

```text
README.md             เริ่มอ่านที่นี่
notebooks/            Google Colab สำหรับสาธิต
source/               CSV จำลองสำหรับ Run 1 และ Run 2
schemas/              ER 1 V3 และ ER 2 V5 (DBML)
pipeline/             Python Modules สำหรับแต่ละขั้น
tests/                Automated Tests
sql/                  SQL ของ Monthly KPI View
docs/                 คู่มือ Mapping และสถานะการทดสอบ
reports/              ผลรันที่เจ้าของโปรเจกต์ตรวจและอัปโหลดหลังทดลอง
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

มีการตรวจ Schema, ทดสอบ SQLite และทดสอบ Logic ของ Pipeline/Recovery ในสภาพแวดล้อมพัฒนาแล้ว รวมถึงทดสอบระบบ Export Reports/Save/Clear Drive ด้วยไฟล์ทดสอบแยก แต่ **ยังไม่ได้ยืนยันการรันครบเส้นทางด้วย DuckDB และ PyArrow จริงบน Google Colab** จึงควรรัน Notebook และเก็บผลทดสอบบน Colab ก่อนนำเสนอหรืออ้างว่า End-to-End ผ่านจริง

ดูขอบเขตการทดสอบและข้อจำกัดได้ที่ [VALIDATION_STATUS.md](docs/VALIDATION_STATUS.md) โดยตรง

## เอกสารประกอบ

- [คู่มือเริ่มต้นและรัน Colab](docs/QUICK_START_TH.md) — สำหรับคนที่อยากลองใช้งานทันที
- [คู่มือ GitHub สำหรับผู้เริ่มต้น](docs/GITHUB_SETUP_TH.md) — สำหรับเจ้าของ Repository
- [โครงสร้าง Pipeline และขอบเขตการทดสอบ](docs/IMPLEMENTATION_BLUEPRINT_TH.md) — สำหรับผู้ตรวจเชิงเทคนิค
- [Source-to-ER 1 Contract](docs/Source_to_ER1_Contract.csv) และ [ER 2 Mapping](docs/ER2_Source_to_Target_Mapping.csv) — สำหรับตรวจการแปลงข้อมูล
- [บทพูดนำเสนอ Demo](docs/DEMO_SCRIPT_FOR_TEACHER_TH.md) — สำหรับการสาธิตหน้าชั้น

