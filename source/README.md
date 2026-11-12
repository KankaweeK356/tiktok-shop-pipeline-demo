# Source สำหรับ Classroom Demo

Source เป็นข้อมูลสังเคราะห์เพื่อการศึกษา. ชุดที่ใช้ใน Colab และหน้า Test Pipeline คือ Source รายเดือนมกราคม–ตุลาคม 2569 จำนวน 10 ZIP; แต่ละชุดมี CSV 21 ตารางตามโครงสร้าง ER1 เดียวกัน

[ดาวน์โหลด Source ZIP ทั้ง 10 เดือน](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/releases/tag/classroom-source-v1) · [ดูตัวสร้าง Source รายเดือน](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/pipeline/generate_classroom_source.py) · [ดู Schema](../schemas/)

Run 1 ใช้ Source เดือนมกราคม. การเติมแต่ละครั้งใช้ Source ของเดือนถัดไปหนึ่งเดือน. จำนวนออเดอร์ขึ้นกับ Source และแสดงจาก manifest/ผลรันจริง

ไฟล์ในโฟลเดอร์ `source/initial` และ `source/incremental` เก็บไว้เป็น fixture สำหรับการทดสอบเดิม; Flow ปัจจุบันเลือกใช้ Source ZIP รายเดือนตามลิงก์ด้านบน. ราคา ส่วนลด COGS และ Commission บางค่าคำนวณจากกฎใน Pipeline ไม่ได้ส่งมาจาก TikTok Shop
