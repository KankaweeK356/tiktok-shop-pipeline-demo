# ผลการรัน Demo

ผลจาก Colab อยู่ใน Notebook และ Runtime ของผู้รัน ไม่ถูกส่งกลับ GitHub, Neon หรือ Dashboard เว็บโดยอัตโนมัติ

## เปิด Notebook ปัจจุบัน

[เปิด Pipeline Notebook ใน Colab](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb) · [ดาวน์โหลด Source ZIP 10 เดือน](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/releases/tag/classroom-source-v1)

หลังแต่ละเดือนประมวลผลสำเร็จ Notebook แสดงสถานะและจำนวนก่อน–หลัง, ผล Validation และข้อมูลจริงแยกชั้น:
- Database ER1: ตารางและจำนวนแถว พร้อมตัวอย่าง 5 แถว
- Data Lake: Landing CSV, Raw Parquet และ Standardized Parquet พร้อมจำนวนแถวและตัวอย่าง
- Warehouse ER2: ตาราง/View และจำนวนแถว พร้อมตัวอย่าง 5 แถว

ไฟล์ผลอยู่ในพื้นที่ `output/colab_classroom/` ของ Runtime; เมื่อ Runtime หมดอายุ ไฟล์ชั่วคราวอาจหาย. ปุ่มเคลียร์ลบผลใน Runtime นั้น โดยคง Source ไว้
