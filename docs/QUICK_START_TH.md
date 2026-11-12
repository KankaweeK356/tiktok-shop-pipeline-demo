# คู่มือเริ่มต้น — Pipeline Demo

[![เปิด Pipeline Demo ใน Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb)

## ใช้หน้าเว็บ

1. เปิด [Test Pipeline](https://tiktok-shop-mlops-dashboard-git-feature-classroom-dea39b-newja.vercel.app/)
2. กด **Run 1** เพื่อรัน Source เดือนมกราคม 2569 ผ่าน 5 ขั้นครบในครั้งเดียว
3. เปิดผลของแต่ละขั้นเมื่อ Run เสร็จ ดูตาราง ตัวอย่างข้อมูล และผลตรวจจริง
4. กด **เติมข้อมูล** เพื่อเพิ่ม Source เดือนถัดไปทีละหนึ่งเดือนจนถึงตุลาคม
5. หาก Run ไม่ผ่าน อ่านขั้น/สาเหตุ แล้วกดปุ่มเดิมเพื่อ Retry เดือนเดิม
6. ใช้ **ทดสอบข้อผิดพลาด** แยกจากรันปกติ หากต้องการสาธิต Error Recovery

Run บนเว็บใช้ Lab Neon และ GitHub Actions ร่วมกัน ผู้ชมที่เปิดลิงก์ไม่จำเป็นต้องมีบัญชี GitHub

## ใช้ Colab เป็นช่องทางสำรอง

เปิด Pipeline Notebook ด้านบน แล้วเลือก **Runtime → Run all** เพื่อเตรียมโปรเจกต์และ Source เท่านั้น จากนั้นใช้ปุ่ม:

- **เริ่มรอบใหม่และรัน Run 1 · มกราคม** — เคลียร์ผลเก่าเฉพาะ Colab Runtime แล้วรันเดือนมกราคม
- **เติมข้อมูลเดือนถัดไป** — เพิ่มครั้งละหนึ่งเดือน ใช้ฐานข้อมูลของ Session เดิม
- **ทดสอบ Error แยก** — ใช้ Workspace ทดสอบแยก ไม่ทำให้ผลปกติล้มเหลว
- **เคลียร์ผลทดลองใน Colab** — ลบ Database, Data Lake, Warehouse และ Error Lab เฉพาะ Runtime นั้น; Source ยังอยู่

Colab ใช้ SQLite, Parquet และ DuckDB ภายใน Runtime ผู้รัน ไม่เชื่อม Neon และผลไม่ขึ้น Dashboard เว็บโดยอัตโนมัติ

## Source และ ER

มี 10 ชุดรายเดือน มกราคม–ตุลาคม 2569; ทุกชุดใช้โครงสร้าง Source CSV 21 ตารางและหัวคอลัมน์เดียวกันตาม ER1. Run 1 มีข้อมูลเดือนมกราคมและตั้ง Master/Reference; Run ถัดไปเพิ่มรายการธุรกิจของเดือนใหม่. ER1 มี 25 ตาราง โดย 4 ตารางเป็นผลที่ Pipeline สร้าง ไม่ได้มาจาก CSV.

## ML

ML ใช้ Feature ระดับสัปดาห์ × กลุ่มสินค้า จาก Warehouse เช่น ยอดขายย้อนหลังและแผน Ads/ส่วนลดที่ทราบก่อนช่วงทำนาย. ต้องมี Feature ที่สมบูรณ์อย่างน้อย 16 สัปดาห์: Train 6 + Validation 2 รอบ รอบละ 3 + Test 4. จึงไม่ถือว่า 1 เดือนเท่ากับ 1 ตัวอย่าง และไม่ฝึกก่อนข้อมูลพร้อม.
