# TikTok Shop Fashion Intelligence — Classroom Demo

เว็บสาธิตการนำ **ข้อมูลขายจำลอง** ผ่าน Database → Data Lake → Data Warehouse แล้วใช้ตรวจ KPI ธุรกิจและทดลองทำ ML ข้อมูลทั้งหมดสร้างเพื่อการศึกษา ไม่ได้เชื่อม TikTok Shop API และไม่ใช่ยอดขายของร้านจริง

**[เปิดเว็บ Demo](https://tiktok-shop-mlops-dashboard-git-feature-classroom-dea39b-newja.vercel.app/)** · [ดู Source CSV](source/README.md) · [ดูโครงสร้างข้อมูล](docs/NEON_CLASSROOM_PIPELINE_ARCHITECTURE_TH.md)

## เริ่มดูจากตรงไหน

| หน้าเว็บ | ทำอะไร | ผลที่ควรเห็น |
| --- | --- | --- |
| **Test Pipeline** | กด Run 1 และ Run 2; แต่ละ Run ประมวลผล Source → Database → Data Lake → Warehouse → Validation ครบเส้นทาง | สถานะและผลจริงของแต่ละขั้น จำนวนก่อน–หลัง ตารางและตัวอย่างแถว |
| **ภาพรวมธุรกิจ** | อ่าน Warehouse ของ Lab รอบปัจจุบัน | เมื่อยังไม่รันหรือเคลียร์แล้ว ต้องแสดงว่าไม่มีข้อมูล; เมื่อรันสำเร็จจึงแสดงผลจากรอบนั้น |
| **ML Lab** | แสดงการสร้าง Feature การแบ่งข้อมูลตามเวลา การฝึก ประเมิน WAPE และตัวอย่างคำทำนาย | ใช้ **Warehouse ประวัติจำลองแยกจาก Test Pipeline**; ผลโมเดลยังไม่ผ่านเกณฑ์ที่ตั้งไว้ |

**สถานะปัจจุบัน:** เว็บรองรับ Run 1 → Run 2 → เคลียร์เพื่อเริ่มรอบใหม่ ยัง **ไม่รองรับ Run 3–7** หรือการฝึก ML ใหม่จาก Warehouse ของ Lab ที่ผู้ชมเพิ่งกดรัน เรื่องนี้เป็นแนวทางพัฒนาที่กำลังออกแบบ ไม่ใช่ฟังก์ชันที่มีแล้ว

### ข้อมูลไหลอย่างไร

1. [Source CSV](source/) แยก `initial` (Run 1), `incremental` (Run 2) และชุดทดสอบ Error
2. Run 1 รับข้อมูล CSV เข้า SQLite ตามแบบ ER1 แล้ว sync ตารางธุรกิจไปยัง **Neon Lab branch ที่แยกไว้**; Run 2 เพิ่มออเดอร์ใหม่และอัปเดตบางรายการในฐานเดิม
3. Data Lake เก็บ Landing CSV, Raw Parquet และ Standardized Parquet
4. DuckDB Warehouse เก็บ Dimensions, Facts, Mart และ KPI View; ขั้น Validation เทียบจำนวนและยอดสำคัญกับฐานข้อมูลต้นทาง
5. เว็บอ่านผล Run ปัจจุบัน; การกดเคลียร์ Lab ล้างข้อมูลทดสอบของรอบนี้ แต่ **ไม่ลบ Source CSV ใน GitHub**

ข้อมูล Run 1 และ Run 2 เป็นชุดที่เตรียมไว้ล่วงหน้าเพื่อรันทดสอบซ้ำได้ จำนวนในไฟล์ Source **ไม่ใช่ผลสำเร็จของ Pipeline**; ให้ดูจำนวนก่อน–หลังและผลตรวจที่หน้าเว็บหลัง Run จบ การกด Run 2 ซ้ำด้วยไฟล์ชุดเดิมไม่ใช่การสร้างชุดข้อมูลใหม่

> **ข้อควรแยก:** Database ต้นทางในเว็บ Lab ใช้ Neon; Data Lake เป็นไฟล์; Warehouse ใช้ DuckDB และไม่ได้เป็นตารางใน Neon โดยตรง ส่วน Error Lab ใช้ข้อมูลทดสอบแยกจาก Run ปกติ

## อยากลองรันโค้ดเองใน Google Colab

Colab รันใน Runtime ของผู้เปิดเองด้วย **SQLite และ DuckDB ในพื้นที่ชั่วคราว** ไม่ต้องมีรหัส Neon/Vercel ไม่เปลี่ยนข้อมูลบนเว็บ และไม่เคลียร์ฐานข้อมูลของคนอื่น

### 1. Pipeline แบบทีละขั้น — แนะนำ

[![เปิด Pipeline Notebook ใน Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb)

เปิด Notebook แล้วเลือก **Runtime → Run all** โปรแกรมจะอ่าน Source, สร้างฐานข้อมูล, Data Lake, Warehouse, ตรวจยอด, เติม Run 2, ทดสอบการส่ง Batch เดิมซ้ำ และทดลอง Error ในพื้นที่แยก ผลแต่ละขั้นอยู่ใต้ Cell และไฟล์อยู่ใน `output/main/` ของ Runtime นั้น การ Run all ซ้ำจะเริ่มพื้นที่ทดลองนี้ใหม่ แต่ไม่ลบ Source หรือ Google Drive

### 2. ML จาก Warehouse — แยกจาก Classroom Lab ปัจจุบัน

[![เปิด ML Notebook ใน Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/notebooks/TikTok_Shop_ML_Study.ipynb)

Notebook นี้สร้างประวัติสังเคราะห์ ผ่าน Pipeline ไปยัง DuckDB Warehouse แล้วสร้าง Feature รายสัปดาห์ ฝึกและเทียบโมเดลด้วย **การแบ่ง Train/Validation/Test ตามเวลา** แสดง WAPE และผลทำนายเทียบยอดจริง ใช้เวลาและทรัพยากรมากกว่า Notebook แรก ผลอยู่ใน `output/ml_history_ci/` ของ Runtime ผู้รันเอง

ML นี้เป็น **offline study**: Feature Store คือชุด Feature ที่จัดเก็บเป็นไฟล์สำหรับการทดลอง ยังไม่ใช่บริการ Feature Store สด; ข้อมูลประวัติแยกจาก Run 1/2 บนเว็บ การมีตัวแปร Ads/แคมเปญในโมเดล **ไม่ได้พิสูจน์** ว่าเพิ่มงบแล้วจะทำให้ยอดขายเพิ่ม ผล WAPE ที่ไม่ผ่านเกณฑ์ต้องรายงานตามจริง ไม่ปรับตัวเลขเพื่อให้ดูผ่าน

## หลักธุรกิจที่ใช้

- **ยอดขายเทียบเป้า:** Net Revenue เทียบ Revenue Target ของเดือนนั้น
- **เกณฑ์รักษากำไร:** Contribution Profit หลังต้นทุนที่เกี่ยวข้อง ÷ Gross Reference Sales (ยอดอ้างอิงก่อนส่วนลด) ต้องไม่น้อยกว่า **10%**
- ค่า Platform Fee 10% และกติกาต้นทุนอื่น ๆ ใน Source เป็น **สมมติฐานของกรณีศึกษา**; `Planning_Adjustable_Gap_Rate = 30%` เป็นกรอบวางแผน ไม่ใช่ผลตอบแทนจาก Ads ที่พิสูจน์แล้ว
- ต้นทุน Ads อยู่ที่ระดับวัน × กลุ่มสินค้า; ไม่ควรอ้างว่าแต่ละ SKU มีกำไรสุทธิหลัง Ads หากยังไม่ได้กำหนดวิธีจัดสรรต้นทุนลง SKU

## ตรวจโค้ดและผลรัน

- [Pipeline Notebook](notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb) · [ML Notebook](notebooks/TikTok_Shop_ML_Study.ipynb)
- [Pipeline CI](.github/workflows/pipeline-ci.yml) · [ML CI](.github/workflows/ml-weekly-demo-ci.yml)
- [Mapping และ Data Dictionary](docs/) · [คำอธิบาย ML รายสัปดาห์](docs/ML_WEEKLY_CLASSROOM_DEMO_TH.md)

เครื่องหมายเขียวใน GitHub Actions ยืนยันการรันบน GitHub เท่านั้น ไม่ใช่การยืนยันว่า Colab ของทุกคนหรือ Neon Lab ขณะนั้นมีผลเหมือนกัน หากต้องการตรวจผลใน Colab ให้ดู Output ของ Runtime ที่ตนรัน ส่วนหน้าเว็บให้อ่านสถานะและผล Run ปัจจุบันจาก Lab

