# ผลการรัน Demo

พื้นที่นี้ใช้เก็บ **รายงานผลการรันบน Google Colab ที่ตรวจสอบแล้ว** เพื่อให้อาจารย์เปิดดูหลักฐานได้โดยไม่ต้องรัน Notebook ก่อน

**สถานะปัจจุบัน:** ยังไม่มีรายงานที่ยืนยันว่าได้รัน End-to-End บน Google Colab ด้วย DuckDB/Parquet จริง จึงไม่ใส่ CSV หรือกราฟสมมติไว้เป็นผลทดสอบ

## หลังทดลองครบแล้วต้องทำอะไร?

1. เปิด [Google Colab Demo](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/main/notebooks/TikTok_Shop_Demo.ipynb)
2. รัน Setup, Run 1, Run 2, Functional/Lineage, Error 6 กรณี และ Performance/Business Results ให้ผ่าน
3. ที่ท้าย Notebook เลือก **เตรียมรายงานสำหรับ GitHub** ระบบจะตรวจว่าได้รันครบและสร้าง `github_report_upload.zip`
4. ดาวน์โหลด ZIP → แตกไฟล์ → อัปโหลดโฟลเดอร์ `reports/` กลับมายัง GitHub และกด Commit changes
5. ตัวเลขในรายงานจะมาจากการรันจริงใน Colab ของคุณ ไม่ใช่ข้อมูลที่แต่งขึ้น

**หมายเหตุ:** การรัน Colab ของคนอื่นจะไม่เขียนกลับ GitHub อัตโนมัติ และไม่กระทบผลลัพธ์ของเจ้าของ Repository
