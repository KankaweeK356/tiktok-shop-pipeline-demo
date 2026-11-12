# Classroom Pipeline — โครงสร้างปัจจุบัน

## วัตถุประสงค์

สาธิตการรับ Source รายเดือน ผ่าน Database → Data Lake → Data Warehouse พร้อม Validation, Dashboard และ ML จากข้อมูลใน Warehouse. ข้อมูลทั้งหมดเป็นข้อมูลสังเคราะห์เพื่อการศึกษา

## Source

- Source มี 10 ชุดรายเดือน มกราคม–ตุลาคม 2569
- Run 1 ใช้เดือนมกราคม; การเติมแต่ละครั้งเพิ่ม Source ของเดือนถัดไปหนึ่งเดือน
- ทุกชุดมี 21 CSV ตาม ER1 contract เดียวกัน; ER1 มี 25 ตาราง โดย 4 ตารางคำนวณจาก Pipeline
- จำนวนข้อมูลจริงแสดงจาก Source manifest และผลหลังรัน

## Flow

1. **Source → Database:** ตรวจ ZIP/CSV, ตาราง, คอลัมน์, Primary Key และความสัมพันธ์ ก่อนนำเข้า ER1
2. **Database → Data Lake:** เก็บ Landing CSV และสร้าง Raw/Standardized Parquet
3. **Data Lake → Warehouse:** Transform และ Load ตาราง Dimension, Fact และ Mart ใน ER2
4. **Validation:** ตรวจจำนวนและยอดระหว่างชั้นข้อมูล พร้อมบันทึกผล PASS/FAIL

หน้าเว็บใช้ Neon เป็น Database และ GitHub Actions รันงาน; Colab ใช้ SQLite, Parquet และ DuckDB ภายใน Runtime ของผู้ใช้ ไม่เชื่อม Neon. ผลของ Colab จึงไม่ขึ้น Dashboard เว็บโดยอัตโนมัติ

## หลักฐานที่ดูหลังรัน

Notebook แสดงผล Database, Data Lake และ Warehouse แยกกัน พร้อมรายชื่อตาราง/ไฟล์ จำนวนแถว และตัวอย่างข้อมูลจริง. Error Lab ใช้พื้นที่แยกจากข้อมูลปกติ. หากขั้นใดไม่ผ่าน ให้อ่านสาเหตุแล้วกดปุ่มเดิมเพื่อรันเดือนเดิมซ้ำ

ดู [คู่มือเริ่มต้น](QUICK_START_TH.md), [ER1/ER2](../schemas/), [Source ZIP](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/releases/tag/classroom-source-v1) และ [Source generator](../pipeline/generate_classroom_source.py)
