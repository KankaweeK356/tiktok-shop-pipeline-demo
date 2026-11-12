# TikTok Shop Fashion Intelligence — Classroom Demo

> **Flow ปัจจุบันของ Classroom Demo คือ Source รายเดือนมกราคม–ตุลาคม 2569**: Run 1 เริ่มที่มกราคม และปุ่มเติมเพิ่มเดือนถัดไปครั้งละหนึ่งเดือน. ไม่ได้กำหนด Run 1 = 800 ออเดอร์ แล้ว Run 2 = เพิ่ม 100 ออเดอร์

**[เปิด Colab Pipeline ปัจจุบัน](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/main/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb)** · [เปิดเว็บ Demo](https://tiktok-shop-mlops-dashboard-git-feature-classroom-dea39b-newja.vercel.app/) · [ดูโค้ด Flow รายเดือน](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/tree/feature/classroom-demo-evidence-foundation)

## อ่านผลใน Colab

หลังรันแต่ละเดือน Notebook แสดง Database → Data Lake → Warehouse พร้อมตาราง/ไฟล์ จำนวนแถว และตัวอย่างข้อมูลจริงที่เลือกดูได้. Colab ใช้ SQLite, Parquet และ DuckDB ใน Runtime ของผู้รัน ไม่เชื่อม Neon Lab และไม่เปลี่ยนข้อมูลบนเว็บ

## ทำไมยังเห็นตัวเลข 800/100 ใน GitHub?

ไฟล์ `source/initial` และ `source/incremental` เป็น fixture รุ่นเดิม: ตุลาคม 800 ออเดอร์ และพฤศจิกายนเพิ่ม 100 ออเดอร์. เป็นชุดเก่าที่ใช้กับการสาธิต October→November ไม่ใช่จำนวนของ Run 1/Run 2 ปัจจุบัน. ดาวน์โหลด [Source ZIP 10 เดือนจาก GitHub Releases](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/releases/tag/classroom-source-v1) หรือโหลดจากหน้า Test Pipeline. Flow รายเดือนสร้างจาก [Source generator](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/pipeline/generate_classroom_source.py); จำนวนของแต่ละเดือนดูจาก manifest และผลรันจริง ไม่ได้ล็อกไว้ที่ 800/100

## โครงสร้างและเอกสาร

- [Source fixtures และคำอธิบายการแยกชุดเก่า/ปัจจุบัน](source/README.md)
- [คู่มือเริ่มต้น](docs/QUICK_START_TH.md)
- [Schema ER1/ER2](schemas/)
- [Pipeline Notebook](notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb)
- [เอกสารและ Workflow รุ่นรายเดือน](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/tree/feature/classroom-demo-evidence-foundation)

**สถานะ GitHub:** โค้ดเว็บ/Source รายเดือนฉบับเต็มอยู่ในสาขา `feature/classroom-demo-evidence-foundation` และ PR #7 ยังเป็น Draft; `main` ยังมีโค้ดเก่าบางส่วน. Notebook ที่ลิงก์ด้านบนใช้ Code จากสาขาปัจจุบันจนกว่าจะรวมสาขา.
