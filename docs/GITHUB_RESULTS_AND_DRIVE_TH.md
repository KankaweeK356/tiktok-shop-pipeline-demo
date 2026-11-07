# วิธีอัปเดต GitHub และเก็บผลการรัน Demo

## 1. อัปเดต Repository เดิม

1. ดาวน์โหลดไฟล์ **TikTok_Demo_GitHub_Update.zip** จาก ChatGPT และแตกไฟล์บนคอมพิวเตอร์
2. เปิด https://github.com/KankaweeK356/tiktok-shop-pipeline-demo
3. เปิดหน้า Repository หลัก → `Add file` → `Upload files`
4. ลาก **ไฟล์และโฟลเดอร์ด้านใน ZIP** ขึ้น GitHub ให้ตำแหน่งตรงกัน เช่น `pipeline/publication.py`, `notebooks/TikTok_Shop_Demo.ipynb`, `reports/README.md`
5. หาก GitHub ไม่รับการแทนที่ไฟล์เดิมผ่านการลาก ให้อัปเดตไฟล์เดิมด้วยเมนู Edit (รูปดินสอ) หรือใช้ GitHub Desktop แทน
6. กด `Commit changes` เมื่อครบ
7. ตรวจว่า `reports/README.md` เปิดได้ และ Notebook บน GitHub ยังอยู่ที่เดิม

> ไม่ต้องสร้าง Repository ใหม่ ไม่ต้องอัปโหลด ZIP ทั้งก้อน และไม่ต้องอัปโหลดไฟล์ `output/` ขึ้น GitHub

## 2. ทดลอง Run 1 และ Run 2

เปิด https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/main/notebooks/TikTok_Shop_Demo.ipynb

รันหัวข้อ 00 → 01 (Run 1) → 02 (Run 2) → 03 (ตรวจยอด) → 04 (Error Tests) → 05 (Performance/Business KPI)

แต่ละคนมี Colab Runtime ของตัวเอง จึงไม่เปลี่ยน Source/Code ใน GitHub

## 3. ทำให้ GitHub มีรายงานผลที่ตรวจแล้ว

ที่ท้าย Notebook หัวข้อ 05.3:

1. ตั้ง `PREPARE_GITHUB_REPORTS=True` แล้วกดรัน
2. ระบบจะ **ไม่สร้างรายงาน** หาก Run 1, Run 2, Functional Test, Error Suite และ Performance ยังไม่ครบหรือไม่ผ่าน
3. หากสร้างผ่านแล้ว ตั้ง `DOWNLOAD_GITHUB_REPORTS_ZIP=True` แล้วกดรันซ้ำเพื่อดาวน์โหลด
4. แตก `github_report_upload.zip` → ได้ `reports/` พร้อมไฟล์ CSV และ README ผลรัน
5. อัปโหลด `reports/` กลับ Repository เดิม แล้วกด `Commit changes`
6. คนตรวจสามารถเปิดไฟล์ที่ `reports/` ได้ทันทีโดยไม่ต้องรัน Colab เอง

**สำคัญ:** ตัวเลขบน GitHub เป็น Snapshot จากผลการรัน Colab ของเจ้าของ Repository เท่านั้น ไม่ใช่ผลสดอัตโนมัติจากผู้ทดลองทุกคน

## 4. บันทึกผลบน Google Drive

ท้าย Notebook หัวข้อ 05.4:

- `DRIVE_ACTION=none` (ค่าเริ่มต้น): ไม่ต้องเชื่อม Drive
- `DRIVE_ACTION=save`: ขอสิทธิ์เชื่อม Google Drive ของผู้รัน และบันทึก Snapshot ที่ `MyDrive/TikTok_Shop_Demo/snapshots/<timestamp>/`
- `DRIVE_ACTION=clear`: เคลียร์ **เฉพาะ** Snapshot ภายใต้โฟลเดอร์ Demo โดยต้องกรอก `CLEAR_CONFIRM=CLEAR_TIKTOK_SHOP_DEMO` เพื่อยืนยัน

คำสั่ง Clear ไม่ลบไฟล์อื่นใน MyDrive ไม่ลบ GitHub และไม่รีเซ็ต Colab Runtime

## 5. ตรวจสิ่งที่อาจารย์ต้องเห็น

- `reports/run1_functional.csv` — ผลตรวจ Initial Load
- `reports/run2_functional.csv` — ผลตรวจ Incremental Load
- `reports/final_functional.csv` — ผลตรวจล่าสุด
- `reports/lineage.csv` — ที่มาของข้อมูลตัวอย่าง
- `reports/error_recovery.csv` — Fail/Retry 6 กรณี
- `reports/performance.csv` — Latency/Throughput จากการรันจริง
- `reports/monthly_kpi.csv` — Revenue, Profit และ Profit Protection
- `reports/product_group_affiliate_scenario.csv` — ทดลองเพดาน Affiliate Commission

ก่อนอ้างว่า Demo ผ่านจริง ต้องได้ผลทดสอบครบเส้นทาง DuckDB/Parquet บน Colab; การตรวจ Syntax หรือ Logic ในเครื่องอื่นเพียงอย่างเดียวไม่พอ
