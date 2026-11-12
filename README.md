# TikTok Shop Fashion Intelligence — Classroom Demo

เว็บสาธิตการนำข้อมูลร้านเสื้อผ้าจำลองผ่าน Source → Database → Data Lake → Data Warehouse แล้วใช้ตรวจ KPI ธุรกิจและทดลอง ML ข้อมูลทั้งหมดสร้างเพื่อการศึกษา ไม่ได้ดึงจาก TikTok Shop API

**[เปิด Colab Pipeline](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb)** · **[เปิดเว็บ Demo](https://tiktok-shop-mlops-dashboard-git-feature-classroom-dea39b-newja.vercel.app/)** · **[ดาวน์โหลด Source รายเดือน 10 ชุด](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/releases/tag/classroom-source-v1)**

## เริ่มรัน

ใน Colab เลือก **Runtime → Run all** เพื่อเตรียม Source และเครื่องมือ จากนั้นกด **เริ่มรอบใหม่และรัน Run 1 · มกราคม**. หากต้องการรันต่อ กด **เติมข้อมูลเดือนถัดไป** เพื่อเพิ่มอีกหนึ่งเดือน ตั้งแต่มกราคมถึงตุลาคม 2569

หลังรัน Notebook แสดงผล Database → Data Lake → Warehouse พร้อมตาราง/ไฟล์ จำนวนแถว และตัวอย่างข้อมูลจริงที่เลือกดูได้. จำนวนออเดอร์ที่เพิ่มมาจาก Source เดือนนั้นและแสดงตามผลรัน

Colab ใช้ SQLite, Parquet และ DuckDB ใน Runtime ของผู้รัน ไม่เชื่อม Neon Lab และไม่เปลี่ยนข้อมูลบนเว็บ

## Source และโครงสร้าง

Source ทั้ง 10 เดือนมี CSV 21 ตารางต่อชุด ตามโครงสร้างและคอลัมน์ ER1 เดียวกัน. ER1 มี 25 ตาราง โดย 4 ตารางสร้างจากการประมวลผลของ Pipeline. ดู [Source ZIP](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/releases/tag/classroom-source-v1), [ตัวสร้าง Source](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/pipeline/generate_classroom_source.py) และ [Schema ER1/ER2](schemas/)

## เอกสาร

- [คู่มือเริ่มต้น](docs/QUICK_START_TH.md)
- [ข้อมูล Source](source/README.md)
- [Pipeline Notebook](notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb)
- [รายละเอียด Flow รายเดือน](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/tree/feature/classroom-demo-evidence-foundation)
