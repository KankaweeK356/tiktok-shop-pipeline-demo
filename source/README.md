# Source สำหรับ Classroom Demo

ชุดข้อมูลของเว็บ Vercel คือ **`classroom_v2_2026_11_16`** เป็นข้อมูลร้านเสื้อผ้าจำลองรายเดือน มกราคม–ตุลาคม 2569 รวม 10 ZIP แต่ละ ZIP มี CSV 21 ตารางตามโครงสร้าง ER1 และ manifest ที่ระบุเดือนและรายละเอียดของไฟล์

- [โฟลเดอร์ดาวน์โหลด ZIP v2](../source_packages/classroom_v2_2026_11_16/)
- [Source Lock สำหรับตรวจ SHA-256](../source_packages/classroom_v2_2026_11_16/source_lock_classroom_v2.json)
- [Schema ER1/ER2](../schemas/)

Run 1 เริ่มจากเดือนมกราคม จากนั้นนำเข้าเดือนถัดไปทีละเดือน ชุดเดือนมีนาคมมีกรณี SKU ผิดสำหรับทดสอบ Review & Fix โดย ZIP เก็บค่าต้นฉบับก่อนแก้

ไฟล์ใน `source/initial` และ `source/incremental` เป็น fixture สำหรับการทดสอบเดิม ส่วน [GitHub Release v1](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/releases/tag/classroom-source-v1) เป็นชุดรุ่นก่อนหน้า
