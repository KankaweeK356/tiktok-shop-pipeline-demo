# TikTok Shop Fashion Intelligence — Classroom Demo

เว็บสาธิตการนำข้อมูลร้านเสื้อผ้าจำลองผ่าน Source → Database → Data Lake → Data Warehouse เพื่อดู KPI และทดลองพยากรณ์ยอดขาย ข้อมูลต้นทางเป็นข้อมูลสังเคราะห์เพื่อการศึกษา

**[เปิดเว็บ Demo บน Vercel](https://tiktok-shop-mlops-dashboard.vercel.app/)** · **[ดาวน์โหลด Source v2 รายเดือน](source_packages/classroom_v2_2026_11_16/)** · **[คู่มือทดลองใช้](docs/QUICK_START_TH.md)**

## ชุดข้อมูลที่ใช้กับเว็บ Demo

ใช้ชุด **`classroom_v2_2026_11_16`** ครบ 10 เดือน ตั้งแต่มกราคมถึงตุลาคม 2569 แต่ละ ZIP มี CSV 21 ตารางตามสัญญาข้อมูล ER1 และ manifest ของเดือนนั้น Pipeline สร้างตาราง ER1 เพิ่มจากการประมวลผลอีก 4 ตาราง

ดาวน์โหลดแยกตามเดือน  
[ม.ค.](source_packages/classroom_v2_2026_11_16/classroom-source-2026-01.zip) · [ก.พ.](source_packages/classroom_v2_2026_11_16/classroom-source-2026-02.zip) · **[มี.ค. · เคสตรวจคุณภาพข้อมูล](source_packages/classroom_v2_2026_11_16/classroom-source-2026-03.zip)** · [เม.ย.](source_packages/classroom_v2_2026_11_16/classroom-source-2026-04.zip) · [พ.ค.](source_packages/classroom_v2_2026_11_16/classroom-source-2026-05.zip) · [มิ.ย.](source_packages/classroom_v2_2026_11_16/classroom-source-2026-06.zip) · [ก.ค.](source_packages/classroom_v2_2026_11_16/classroom-source-2026-07.zip) · [ส.ค.](source_packages/classroom_v2_2026_11_16/classroom-source-2026-08.zip) · [ก.ย.](source_packages/classroom_v2_2026_11_16/classroom-source-2026-09.zip) · [ต.ค.](source_packages/classroom_v2_2026_11_16/classroom-source-2026-10.zip)

ตรวจตัวไฟล์ด้วย [Source Lock (SHA-256 รายเดือน)](source_packages/classroom_v2_2026_11_16/source_lock_classroom_v2.json) ผลเทียบ Production วันที่ 21 พ.ย. 2569 ใน Demo Cycle 41 พบว่า ZIP ทั้ง 10 เดือนตรงกับ Source Lock และเดือน ม.ค.–พ.ค. ตรงกับ hash ที่บันทึกทั้งใน Run และ Published Snapshot

## เคสสาธิตเดือนมีนาคม

ไฟล์เดือนมีนาคมเก็บข้อมูลต้นฉบับก่อนแก้ โดยมีรายการ SKU ที่ไม่ผ่านการตรวจคุณภาพข้อมูล เมื่อทดลองในระบบที่ได้รับอนุมัติ ให้เปิด **Review & Fix** เทียบกับบิล เลือกค่าที่ถูกต้อง แล้ว **Revalidate → Resume** ผลหลัง Publish อ้างอิงชุดแก้ไขที่บันทึกในระบบ ส่วน ZIP ต้นทางใช้สำหรับเริ่มทดสอบซ้ำ

## ช่องทางทดลองและเอกสาร

- [เว็บ Demo](https://tiktok-shop-mlops-dashboard.vercel.app/) ใช้ดูข้อมูลที่ Publish แล้ว สำหรับการรันและแก้ข้อมูลให้ใช้สภาพแวดล้อมทดสอบที่ได้รับอนุมัติ
- [คู่มือเริ่มต้น](docs/QUICK_START_TH.md) และ [รายละเอียดชุดต้นทาง](source/README.md)
- [Schema ER1/ER2](schemas/)
- [Colab รุ่นก่อนหน้า](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb) ใช้ SQLite, Parquet และ DuckDB ใน Runtime ของผู้รัน ส่วน [GitHub Release v1](https://github.com/KankaweeK356/tiktok-shop-pipeline-demo/releases/tag/classroom-source-v1) เก็บไว้สำหรับการทดลองรุ่นเดิม
