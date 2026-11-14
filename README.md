# TikTok Shop Fashion Intelligence — Classroom Demo

เว็บสาธิตการนำข้อมูลร้านเสื้อผ้าจำลองผ่าน Data Pipeline ตั้งแต่ต้นทางจนถึงปลายทาง: **Source (CSV) ➔ Database (Neon) ➔ Data Lake (Parquet) ➔ Data Warehouse (DuckDB)** พร้อมการวิเคราะห์ KPI ธุรกิจและโมเดลทำนายยอดขาย ML โดยข้อมูลทั้งหมดเป็นข้อมูลสังเคราะห์เพื่อการศึกษา ไม่ได้ดึงจาก TikTok Shop API

**[เปิดเว็บ Demo](https://tiktok-shop-mlops-dashboard-git-feature-classroom-dea39b-newja.vercel.app/)** · [ดูตัวสร้าง Source](pipeline/generate_classroom_source.py) · [ดู Schema ER1/ER2](schemas/)

---

## 1. สถาปัตยกรรมระบบ (Architecture)

- **Source Code**: จัดเก็บและควบคุมเวอร์ชันบน **GitHub**
- **Web & ETL Processing**: โฮสต์และ**ประมวลผลบน Vercel (Vercel Native Runner)** โดยตรง
  - เมื่อผู้ใช้กดปุ่ม Run บนเว็บ Vercel จะเป็นผู้เริ่มและประมวลผล ETL โดยตรง ไม่พึ่งพา GitHub Actions เป็นตัวรันงาน
  - ประมวลผลรวดเร็วและต่อเนื่องด้วยระบบ Checkpoint แบบ Idempotent
- **Database (Neon Serverless PostgreSQL)**: แยก Branch เพื่อความปลอดภัยของข้อมูล
  - `classroom-live-run-lab`: สำหรับ Run 1 และการเติมข้อมูลปกติรายเดือน
  - `classroom-error-lab`: สำหรับการทดสอบ Error Test โดยไม่กระทบข้อมูลธุรกิจ
- **Data Lake & Storage**: จัดเก็บ Raw/Standardized Parquet และ Workspace State บน Neon Object Storage (S3-compatible)
- **Data Warehouse**: ประมวลผลและสร้าง Data Mart บน DuckDB แบบ Columnar In-Memory

---

## 2. ขั้นตอนการประมวลผล 5 ขั้น และการจัดแบ่ง Input / Output

| ขั้นตอน | ข้อมูลขาเข้า (Input) | การประมวลผล (Process) | ข้อมูลขาออก (Output) & การนำไปใช้ |
| :--- | :--- | :--- | :--- |
| **1. Source ➔ Database** | **ไฟล์ CSV 21 ไฟล์** จากโฟลเดอร์รายเดือน | ตรวจ Schema, Foreign Key และนำเข้าสู่ Neon PostgreSQL | **25 ตาราง Database** ใน `demo_er1` (21 ตารางจาก CSV + 4 ตารางคำนวณและคลัง FIFO) |
| **2. Database ➔ Data Lake** | 25 ตาราง Database | สกัดข้อมูลรายเดือน แบ่ง Partition ตามงวดบัญชี | **25 ไฟล์ Data Lake Parquet** (Snappy Compressed) ใน `lake/raw/{batch}/` |
| **3. Transform & Quality Check** | 25 ไฟล์ Data Lake Raw | จัดมาตรฐานข้อมูล (Type casting, Dates, Status) และตรวจกฎคุณภาพ (Null, FK, Campaign Overlap) | **ชุดข้อมูล Data Lake Standardized** ใน `lake/standardized/{batch}/` และบันทึก Quarantine หากพบข้อผิดพลาด |
| **4. Data Lake ➔ Warehouse** | Data Lake Standardized | โหลดข้อมูลลง Star Schema และสร้าง Materialized Aggregation Marts ใน DuckDB | **ตาราง Warehouse ใน DuckDB** (`View_Shop_Monthly_KPI`, `Mart_Product_Group_Daily_Performance`, `Fact_Sales_Order_Item`) เชื่อมโยงสู่ Dashboard |
| **5. Validate** | ทั้ง 4 เลเยอร์ | ตรวจกระทบยอด Cross-Layer Reconciliation และตรวจสอบยอดเงินสุทธิ | **รายงานผลตรวจ 100% Reconciliation** ยืนยันยอดขายสุทธิ $Source = Warehouse$ |

---

## 3. การแสดงผลบน Dashboard (Master-Detail Split View)

- หน้าจอแสดงผลแบบ **Two-Column Split Layout**: ฝั่งซ้ายแสดงรายการตาราง/ไฟล์ และฝั่งขวาแสดงรายละเอียดเชิงลึก (ชื่อ, ชนิดข้อมูล, จำนวนแถวจริง, คอลัมน์, ตัวอย่างข้อมูล 5 แถว และตาราง Dashboard/KPI ที่นำไปใช้) ทันทีเมื่อคลิกเลือก โดยไม่ต้องเลื่อนหน้าจอ
- การแยกคำศัพท์มาตรฐาน:
  - **ไฟล์ CSV (CSV File)**: ไฟล์ข้อความต้นทาง
  - **ตาราง Database (Database Table)**: ตารางใน Neon PostgreSQL
  - **ชุดข้อมูล/ไฟล์ Data Lake (Data Lake Parquet)**: ไฟล์ Parquet คอลัมน์
  - **ตาราง Warehouse (Warehouse Table)**: ตาราง Fact/Dim ใน DuckDB

---

## 4. รอบการรันรายเดือนและการสาธิต Error

- **ข้อมูล 10 ชุดรายเดือน (มกราคม–ตุลาคม 2569)**:
  - **Run 1 (initial)**: นำเข้าข้อมูลเดือนมกราคม 2569
  - **Run เติมข้อมูล (incremental_01 ถึง incremental_09)**: เติมข้อมูลเดือนกุมภาพันธ์ถึงตุลาคม 2569 ทีละเดือนอย่างต่อเนื่อง
- **การสาธิต Error ในเดือนที่ 3 (มีนาคม)**:
  - มีปุ่มเลือกสาธิตกรณีข้อมูลผิดพลาดในเดือนที่ 3 (จำลอง SKU ไม่ตรงใน `Fact_Order_Items`)
  - ระบบจะตรวจพบในขั้น **Transform / Quality Check** และทำการกักข้อมูล (Quarantine) ไว้
  - **รับประกันความปลอดภัย**: ข้อมูลเดือน 3 จะไม่ถูกส่งเข้า Warehouse และข้อมูลเดือน 1-2 ยังคงปลอดภัยสมบูรณ์
  - ผู้ใช้สามารถกดปุ่ม *"รันต่อด้วยข้อมูลฉบับแก้ไข"* เพื่อดึง Source ปกติของเดือน 3 และรันต่อจาก Checkpoint ได้ทันที

---

## 5. การรันใน Google Colab (สภาพแวดล้อมสำรอง)

- Colab รันใน Runtime ของผู้ใช้เองอย่างอิสระ ไม่เชื่อมต่อกับ Neon และผลลัพธ์ใน Colab จะไม่แสดงบนเว็บ Dashboard
- [เปิด Pipeline Notebook ใน Colab](notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb): กด **Runtime → Run all** แล้วใช้ปุ่มควบคุมด้านล่างเพื่อทดลองรัน Run 1 และเติมข้อมูลทีละเดือน
- [เปิด ML Notebook ใน Colab](notebooks/TikTok_Shop_ML_Study.ipynb): ศึกษาการสร้าง Feature จาก Warehouse และการฝึกโมเดล ML (ต้องมีอย่างน้อย 16 สัปดาห์)

---

## 6. เอกสารและข้อมูลอ้างอิง

- [คู่มือเริ่มต้นด่วน (Quick Start)](docs/QUICK_START_TH.md)
- [บทพูด Demo สำหรับอาจารย์](docs/DEMO_SCRIPT_FOR_TEACHER_TH.md)
- [สถาปัตยกรรม Neon Pipeline](docs/NEON_CLASSROOM_PIPELINE_ARCHITECTURE_TH.md)
- [คำอธิบายชุดข้อมูล Source](source/README.md)
