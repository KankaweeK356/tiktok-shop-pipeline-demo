# คู่มือเริ่มต้น — Classroom Pipeline Demo

> ใช้ Flow รายเดือนปัจจุบัน: Run 1 = มกราคม 2569 และเติมเดือนถัดไปครั้งละหนึ่งเดือนจนถึงตุลาคม. ไฟล์ `source/initial` (800 ออเดอร์เดือนตุลาคม) และ `source/incremental` (100 ออเดอร์เดือนพฤศจิกายน) เป็น fixture เก่า ไม่ใช่จำนวน Run 1/Run 2 ปัจจุบัน

[![เปิด Pipeline Demo ใน Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb)

## ดาวน์โหลด Source รายเดือน\n\n[เปิด GitHub Release ที่มีไฟล์ ZIP มกราคม–ตุลาคม 2569](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/releases/tag/classroom-source-v1).\n\n## เริ่มรัน

1. ใน Colab เลือก **Runtime → Run all** เพื่อเตรียม Code และ Source
2. กด **เริ่มรอบใหม่และรัน Run 1 · มกราคม**
3. ดูผลแต่ละขั้นและผลจริงของ Database, Data Lake และ Warehouse
4. กด **เติมข้อมูลเดือนถัดไป** เพื่อเพิ่มอีกหนึ่งเดือน
5. จำนวนออเดอร์ที่เพิ่มเปลี่ยนตาม Source ของเดือนนั้น ไม่ได้เพิ่ม 100 ทุกครั้ง

Colab ใช้ SQLite, Parquet และ DuckDB ภายใน Runtime ของผู้รันเอง ไม่เชื่อม Neon Lab และไม่อัปเดต Dashboard เว็บ

## ดูข้อมูลแต่ละชั้น

หลังรันสำเร็จ เปิดหัวข้อ Database, Data Lake และ Warehouse เพื่อดูรายชื่อตาราง/ไฟล์ จำนวนแถว และเลือกดูตัวอย่าง 5 แถวจากข้อมูลจริง

## สถานะสาขา

Notebook ใช้ Code จาก [สาขา Classroom Demo ปัจจุบัน](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/tree/feature/classroom-demo-evidence-foundation). ตัวเว็บและ Source รายเดือนฉบับเต็มยังอยู่ในสาขานี้; `main` มี Code รุ่นเดิมบางส่วนขณะ PR #7 ยังเป็น Draft.
