# คู่มือเริ่มต้น — Classroom Pipeline Demo

[![เปิด Pipeline Demo ใน Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb)

[ดาวน์โหลด Source ZIP รายเดือน มกราคม–ตุลาคม 2569](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/releases/tag/classroom-source-v1)

## เริ่มรัน

1. ใน Colab เลือก **Runtime → Run all** เพื่อเตรียม Code และ Source
2. กด **เริ่มรอบใหม่และรัน Run 1 · มกราคม**
3. หลังรันเสร็จ ดูผลแต่ละขั้นใน Database, Data Lake และ Warehouse
4. กด **เติมข้อมูลเดือนถัดไป** เพื่อเพิ่มทีละหนึ่งเดือน
5. หากรันไม่ผ่าน ให้อ่านขั้นและสาเหตุ แล้วกดปุ่มเดิมเพื่อลองเดือนเดิมอีกครั้ง

## ดูผลข้อมูล

เปิดหัวข้อ Database, Data Lake และ Warehouse เพื่อดูรายชื่อตาราง/ไฟล์ จำนวนแถว และเลือกดูตัวอย่างข้อมูลจริง. Colab ใช้ SQLite, Parquet และ DuckDB ใน Runtime ของผู้รัน ไม่เชื่อม Neon Lab และผลไม่แสดงใน Dashboard เว็บ
