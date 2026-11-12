# ผลการรัน Demo

ผลจาก Colab แสดงอยู่ใน Notebook และในพื้นที่ Runtime ของผู้รัน ไม่ถูกส่งกลับ GitHub, Neon หรือ Dashboard เว็บโดยอัตโนมัติ

## Notebook ปัจจุบัน

เปิด [Pipeline Notebook ใน Colab](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb) เลือก **Runtime → Run all** เพื่อเตรียมโปรเจกต์ แล้วใช้ปุ่มเริ่ม Run 1 และเติมเดือนถัดไปครั้งละหนึ่งเดือน

## ผลและไฟล์

- ผลแต่ละ Run แสดงจำนวนก่อน–หลัง, Validation, ตัวอย่าง Warehouse และเวลาที่วัดจาก Runtime ปัจจุบัน
- ไฟล์อยู่ที่ `output/colab_classroom/main/` ภายใน Runtime; เมื่อ Runtime หมดอายุ พื้นที่ชั่วคราวอาจหายไป
- ปุ่มเคลียร์ใน Notebook ลบผล Pipeline และ Error Lab ใน Runtime นั้น โดยคง Source ไว้
- ผล Colab แยกจาก Lab Neon บนเว็บ; ผู้ใช้ต้องเปิด Test Pipeline เพื่อดู Run ที่ทำผ่านเว็บ
