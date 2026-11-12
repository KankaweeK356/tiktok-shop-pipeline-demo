# ผลการรัน Demo

ผลจาก Colab แสดงอยู่ใน Notebook และพื้นที่ Runtime ของผู้รัน ไม่ถูกส่งกลับ GitHub, Neon หรือ Dashboard เว็บโดยอัตโนมัติ

## Notebook ปัจจุบัน

[เปิด Pipeline Notebook ใน Colab](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb). เลือก **Runtime → Run all** เพื่อเตรียมโปรเจกต์ แล้วกดปุ่มเริ่ม Run 1 และเติมเดือนถัดไปครั้งละหนึ่งเดือน

## ผลที่ Notebook แสดง

หลังแต่ละเดือนประมวลผลสำเร็จ Notebook แสดงเวลา/สถานะของขั้น, จำนวนก่อน–หลัง, ผล Validation และหลักฐานข้อมูลแยกชั้น:
- Database ER1: ตารางและจำนวนแถว พร้อมเลือกดูตัวอย่าง 5 แถว
- Data Lake: ไฟล์ Landing CSV, Raw Parquet และ Standardized Parquet พร้อมจำนวนแถวและตัวอย่าง
- Warehouse ER2: ตาราง/View และจำนวนแถว พร้อมเลือกดูตัวอย่าง 5 แถว

จำนวนออเดอร์ของแต่ละเดือนมาจาก Source manifest และผล Pipeline จริง ไม่มีการล็อก Run 1 เป็น 800 หรือ Run 2 เพิ่ม 100. ตัวเลข 800/100 เป็นของ fixture เก่าตุลาคม/พฤศจิกายน ไม่ใช่ยอดเพิ่มรายเดือนของ Flow ปัจจุบัน

ผลอยู่ในพื้นที่ `output/colab_classroom/` ภายใน Runtime; เมื่อ Runtime หมดอายุ ไฟล์ชั่วคราวอาจหาย. ปุ่มเคลียร์ลบผล Pipeline และ Error Lab ใน Runtime นั้น โดยคง Source ไว้
