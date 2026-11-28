# รัน Demo ด้วย Docker (สำหรับรุ่นต่อไป / ผู้ที่อยากทดลองเอง)

โปรเจกต์: TikTok Shop Fashion Intelligence — MADT8102 Seminar in Advanced Analytics System Implementation

ไฟล์ Docker นี้รัน **Data Pipeline ครบ 5 ขั้น** (Ingest → Extract → Transform → Load → Validate) บนเครื่องของคุณเอง
ตลอด **10 เดือน** (ม.ค.–ต.ค. 2026) พร้อมตัวอย่าง **ข้อมูลผิดของเดือนมีนาคม** ที่ถูก Data Quality Gate บล็อก
ไม่ต้องมีบัญชี Neon / Vercel / GitHub / Cloud ใด ๆ ใช้เวลารันประมาณ 1–2 นาที

> ข้อมูลเป็นข้อมูลจำลองเพื่อการเรียน (ไม่ใช่ข้อมูล TikTok จริง) สร้างซ้ำได้เหมือนเดิมทุกครั้ง (กำหนด seed คงที่)

## สิ่งที่ต้องมี

- ติดตั้ง Docker (Docker Desktop บน Windows/Mac หรือ Docker Engine บน Linux)

## วิธีรัน

เปิด Terminal ที่โฟลเดอร์โปรเจกต์ (ที่มีไฟล์ `Dockerfile`) แล้วพิมพ์

```bash
docker build -t tiktok-shop-pipeline .
```

```bash
docker run --rm tiktok-shop-pipeline
```

ถ้าอยากเก็บไฟล์ผลลัพธ์ (ฐานข้อมูล / Data Lake / Warehouse) ไว้ในเครื่อง ใช้ docker compose แทน

```bash
docker compose up --build
```

ไฟล์ผลลัพธ์จะอยู่ในโฟลเดอร์ `output/docker_demo/` ของเครื่องคุณ

## ตัวเลือก

```bash
docker run --rm tiktok-shop-pipeline python docker/run_demo.py --months 3
```

รันแค่ 3 เดือนแรก (ใช้เวลาไม่ถึง 20 วินาที)

```bash
docker run --rm tiktok-shop-pipeline python docker/run_demo.py --no-error-demo
```

ข้ามส่วนสาธิตข้อมูลผิดของเดือนมีนาคม

## ผลที่จะเห็น

แต่ละเดือนจะแสดง

- เวลาที่ใช้ในแต่ละขั้นทั้ง 5
- ผล DQ Gate (กฎที่ผ่าน / ไม่ผ่าน / ไม่เกี่ยวข้องกับตารางในชุดนี้)
- ผลกระทบยอด ER1 เทียบ ER2 (เช่น `21/21 checks passed` และ Net Revenue ตรงกัน)

เดือนมีนาคมจะเห็น **ระบบหยุดที่ขั้น Ingest** เพราะกฎ

```
REFERENCE_EXISTS:Fact_Order_Items.SKU_ID -> Dim_SKU.SKU_ID
```

ตก (มีรายการสินค้าที่อ้างถึง SKU ที่ไม่มีอยู่จริง) โดยยังไม่เขียนอะไรลงฐานข้อมูล จากนั้นรันชุดข้อมูลที่ถูกต้องต่อได้

ตอนท้ายจะแสดงตาราง KPI รายเดือนจาก Warehouse (Gross, Net Revenue, กำไร, ผลตามเกณฑ์กำไรขั้นต่ำ)

## โครงสร้างของระบบใน Docker

```
CSV 10 ชุดรายเดือน (21 ตารางต่อเดือน)
   → ER1 (SQLite, 25 ตาราง)
   → Data Lake (Parquet: raw → standardized)
   → ER2 (DuckDB, 11 ตาราง + 1 View: Star Schema + Mart)
```

เวอร์ชันเว็บ Dashboard ที่ใช้นำเสนอ (Vercel + Neon) ไม่ได้อยู่ใน Docker นี้ เพราะต้องใช้บริการคลาวด์
ดูรายละเอียดทั้งระบบได้ที่ `README.md` และเอกสารในโฟลเดอร์ `docs/`

## ไฟล์ที่เกี่ยวข้อง

| ไฟล์ | หน้าที่ |
|---|---|
| `Dockerfile` | สูตรสร้างกล่อง (Python 3.12 + ไลบรารี + โค้ด Pipeline) |
| `docker-compose.yml` | สั่งรันและเก็บผลลัพธ์ไว้ในเครื่อง |
| `docker/requirements.txt` | ไลบรารีที่ใช้ (pandas, numpy, pyarrow, duckdb) |
| `docker/run_demo.py` | สคริปต์รันทั้ง 10 เดือนและแสดงผล |
| `.dockerignore` | ไฟล์ที่ไม่ต้องใส่ในกล่อง |
