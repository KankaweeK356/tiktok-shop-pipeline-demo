# คู่มือเริ่มต้น — Classroom Pipeline Demo

[เปิดเว็บ Demo](https://tiktok-shop-mlops-dashboard.vercel.app/) · [ดาวน์โหลด Source v2 รายเดือน มกราคม–ตุลาคม 2569](../source_packages/classroom_v2_2026_11_16/)

## ทดลองบนเว็บ

เว็บ Production ใช้เปิดดูข้อมูลที่ Publish แล้ว สำหรับขั้นตอนที่รัน แก้ หรือบันทึกข้อมูล ให้ใช้สภาพแวดล้อมทดสอบที่ได้รับอนุมัติ

1. เริ่มรอบ Demo แล้วรัน ม.ค. และ ก.พ. ให้ขึ้น Published
2. รัน มี.ค. เปิด Review & Fix เมื่อระบบแจ้งว่ามีรายการไม่ผ่าน เทียบ SKU กับบิล ยืนยันค่าที่ถูกต้อง แล้วกด Revalidate และ Resume
3. รัน เม.ย. และ พ.ค. ให้ขึ้น Published แล้วสร้าง Forecast เดือน มิ.ย. ด้วยข้อมูลถึง พ.ค. จากนั้นบันทึกและล็อก Forecast
4. ทดลอง Scenario A/B/C แล้วบันทึกแผนที่เลือก
5. รันและ Publish มิ.ย. แล้วเปิดคาดการณ์เทียบผลจริงและภาพรวมธุรกิจของเดือนเดียวกัน

## ทดลองใน Colab รุ่นก่อนหน้า

[เปิด Notebook รุ่นก่อนหน้า](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb) · [Source Release v1 ของรอบเดิม](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/releases/tag/classroom-source-v1)

ใน Colab เลือก **Runtime → Run all** แล้วกดเริ่ม Run 1 เดือนมกราคมและเพิ่มเดือนถัดไปตามลำดับ Notebook แสดง Database, Data Lake และ Warehouse ใน Runtime ของผู้รัน โดยใช้ SQLite, Parquet และ DuckDB
