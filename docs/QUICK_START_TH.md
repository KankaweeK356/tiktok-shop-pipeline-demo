# คู่มือเริ่มต้น — Classroom Pipeline Demo

> **ใช้ Notebook นี้สำหรับ Flow ปัจจุบัน:** Run 1 = Source เดือนมกราคม 2569 และเติม Source เดือนถัดไปครั้งละหนึ่งเดือนจนถึงตุลาคม. อย่าใช้ตัวเลข 800 orders + 100 orders เป็นจำนวน Run 1/Run 2; ตัวเลขนั้นมาจาก Source fixture รุ่นเก่า

[![เปิด Pipeline Demo ใน Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb)

## Colab

1. เปิด Notebook แล้วเลือก **Runtime → Run all** เพื่อเตรียม Source และเครื่องมือ
2. กด **เริ่มรอบใหม่และรัน Run 1 · มกราคม**
3. รอผลทั้ง 5 ขั้น แล้วดูฐานข้อมูล, Lake และ Warehouse ในหัวข้อผลลัพธ์
4. กด **เติมข้อมูลเดือนถัดไป** เพื่อเพิ่มอีกหนึ่งเดือน; จำนวนออเดอร์ที่เพิ่มแสดงตาม Source จริงของเดือนนั้น
5. หาก Pipeline ไม่ผ่าน ให้อ่านขั้นและสาเหตุ แล้วกดปุ่มเดิมเพื่อลองเดือนเดิมอีกครั้ง

หลังรัน แต่ละชั้นแสดงรายชื่อตาราง/ไฟล์ จำนวนแถว และเลือกเปิดตัวอย่าง 5 แถวได้:
- **Database · ER1** — ตารางฐานข้อมูลและจำนวนแถว
- **Data Lake** — Landing CSV, Raw Parquet และ Standardized Parquet
- **Warehouse · ER2** — ตารางและ View หลัง Transform/Load/Validate

Colab ใช้ SQLite, Parquet และ DuckDB ใน Runtime ของผู้รันเอง ไม่เชื่อม Neon และผลไม่แสดงใน Dashboard เว็บ

## จำนวนและโครงสร้าง Source

ตัวสร้าง [Source รายเดือน](../pipeline/generate_classroom_source.py) สร้าง 10 ชุด มกราคม–ตุลาคม โดยทุกเดือนมี CSV 21 ตารางตามโครงสร้างและคอลัมน์ ER1 เดียวกัน. Run 1 ส่ง Master/Reference และข้อมูลธุรกิจเดือนมกราคม; Run ต่อไปส่งรายการธุรกิจของเดือนใหม่ โดยคงตาราง Master/Reference ไว้ใน ZIP ตาม Contract.

จำนวนออเดอร์ไม่กำหนดเป็น 800, 900 หรือเพิ่มทีละ 100. ระบบใช้จำนวนตาม Source ของเดือนนั้นและรายงานก่อน–หลังจากผลรันจริง. ไฟล์ `source/initial` และ `source/incremental` เป็น fixture เก่าสำหรับกรณีตุลาคม 800 ออเดอร์/พฤศจิกายนเพิ่ม 100 ออเดอร์; ไม่ใช่คู่ Run 1/Run 2 ใน Flow รายเดือนปัจจุบัน. 800 ออเดอร์นั้นอยู่ใน delivery เดือนตุลาคม; 100 ออเดอร์พฤศจิกายนไม่ถูกรวมในช่วงมกราคม–ตุลาคม.

## ลิงก์สำคัญ

- [README โครงการ](../README.md)
- [ER1 / ER2](../schemas/)
- [Source generator](../pipeline/generate_classroom_source.py)
- [ผลใน Colab Runtime](../reports/README.md)
