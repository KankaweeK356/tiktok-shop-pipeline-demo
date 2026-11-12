# Source fixtures และ Source รายเดือน

ข้อมูลทั้งหมดเป็นข้อมูลสังเคราะห์เพื่อการศึกษา ไม่ได้ดึงจาก TikTok Shop API และไม่มีข้อมูลลูกค้าหรือการเงินจริง

## แยกชุดเก่ากับ Flow ปัจจุบัน

ไฟล์ CSV ใน `source/initial/` และ `source/incremental/` เป็น fixture รุ่นเดิม: October 2026 มี 800 Orders และ November 2026 มี 100 Orders ใหม่ พร้อมกรณีเปลี่ยนสถานะ/ปรับข้อมูลปลายงวด. ใช้สำหรับการทดสอบ October→November รุ่นเดิม

**ตัวเลข 800/100 ไม่ใช่จำนวน Run 1/Run 2 ปัจจุบัน.** Colab Step-by-Step ใช้ Code จากสาขา Classroom Demo ปัจจุบันและสร้าง 10 Source deliveries รายเดือน January–October 2026. Run 1 คือ January; การเติมแต่ละครั้งคือเดือนถัดไปหนึ่งเดือน. จำนวนออเดอร์ขึ้นกับข้อมูลจริงใน Source เดือนนั้น และดูได้จาก manifest/ผล Pipeline. Fixture 800 Orders เป็นข้อมูลของ October; fixture 100 Orders เดือน November อยู่นอกช่วงรายเดือนนี้

ทุก delivery รายเดือนมีโครงสร้าง CSV 21 ตารางและหัวคอลัมน์ตาม ER1 contract. ดู [Source generator](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/pipeline/generate_classroom_source.py) และ [คู่มือปัจจุบัน](QUICK_START_TH.md).

ราคา ส่วนลด COGS และ Commission บางค่าได้จากกฎใน Pipeline ไม่ใช่ค่าที่บันทึกใน CSV.
