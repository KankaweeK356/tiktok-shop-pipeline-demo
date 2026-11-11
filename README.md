# TikTok Shop Fashion Intelligence — Classroom Demo

เว็บสาธิตการใช้ **ข้อมูลร้านเสื้อผ้าจำลอง** ผ่าน Source → Database → Data Lake → Data Warehouse แล้วอ่าน KPI และทดลอง ML ข้อมูลทั้งหมดเป็นข้อมูลสังเคราะห์เพื่อการศึกษา ไม่ได้ดึงจาก TikTok Shop API

**[เปิดเว็บ Demo](https://tiktok-shop-mlops-dashboard-git-feature-classroom-dea39b-newja.vercel.app/)** · [ดูตัวสร้าง Source](pipeline/generate_classroom_source.py) · [ดูแบบ ER1/ER2](schemas/)

## ทดลองบนเว็บ

| หน้า | สิ่งที่ทำ | สิ่งที่ดู |
| --- | --- | --- |
| **Test Pipeline** | กด Run 1 เพื่อรับข้อมูลตั้งต้น แล้วกด **เติมข้อมูลใหม่** ทีละชุด | แต่ละครั้งรัน Source → Neon Database → Parquet Data Lake → DuckDB Warehouse → Validation ครบ ดู PASS/FAIL ตารางและแถวจริงได้หลังรัน |
| **ภาพรวมธุรกิจ** | ดู Warehouse ของ Lab รอบปัจจุบัน | ยอดสุทธิเทียบเป้ารายเดือน กำไรเทียบเกณฑ์ 10% และเจาะเดือน → กลุ่มสินค้า → วัน/SKU/แคมเปญ |
| **ML Lab** | กดฝึกโมเดลจาก Warehouse รอบปัจจุบัน | Feature รายสัปดาห์ การแบ่ง Train/Validation/Test WAPE ยอดจริงเทียบคำทำนาย และทดลองแผน Ads/ส่วนลด |

### Source และรอบการรัน

ตัวสร้าง Source ใช้ seed เดียวกันทุกครั้งและส่งออก CSV **7 ชุด** ภายใต้ `output/classroom_source/` ใน GitHub Worker: `initial` มีประวัติประมาณ 12 เดือน; `incremental_01` ถึง `incremental_06` เป็นข้อมูลเติมต่อเนื่อง ชุดแรกมีการอัปเดตออเดอร์เดิมด้วย ทุกชุดใช้โครงสร้าง ER1 เดิม 25 ตาราง ไม่มีตารางธุรกิจเพิ่ม ชุดข้อมูลเป็น Source แยกจาก Neon และจากผล Data Lake/Warehouse

บนเว็บผู้ชมเห็นเพียง **Run 1** และปุ่ม **เติมข้อมูลใหม่** ไม่ต้องเลือกลำดับชุดเอง ระบบเลือก Source ชุดที่ยังไม่ผ่านรอบปัจจุบันถัดไป เมื่อใช้ครบจะบอกว่าไม่มี Source ใหม่และไม่สร้างผลปลอม จำนวนออเดอร์ก่อน–หลังและยอดขายจะแสดงจากผลรัน ไม่แสดงผลล่วงหน้า หากรันปกติไม่ผ่าน ให้ดูสาเหตุใน Log และกดปุ่มเดิมเพื่อลองชุดเดิมอีกครั้ง; Error Lab เป็นชุดทดลองปัญหาที่แยกต่างหาก

ปุ่ม **เคลียร์ข้อมูล Lab** ลบข้อมูลธุรกิจใน Neon ของรอบปัจจุบันและเริ่มรอบใหม่ ข้อมูล Warehouse/ML รอบเก่าไม่ถูกนำมาแสดงเป็นข้อมูลปัจจุบัน ไฟล์ Source ไม่ถูกลบ Log GitHub เก่าเก็บไว้ตรวจย้อนหลัง หากเว็บยังแสดงรอบข้อมูลที่สร้างด้วยระบบสองชุดเดิม ให้เคลียร์ Lab หลังตรวจว่าไม่มีงานกำลังรัน เพื่อเริ่มชุด 7 Source รุ่นใหม่นี้

> Neon เก็บ ER1 Database จริง ส่วน Data Lake เป็นไฟล์ Parquet และ Warehouse เป็น DuckDB ใน GitHub Actions Artifact จึงไม่เห็นตาราง Warehouse ใน Neon Console โดยตรง หน้า Test Pipeline มีตัวอย่างแถวจริงและปุ่มไปดู Neon ER1 แบบอ่านอย่างเดียว

### KPI และ ML

**ยอดขายเทียบเป้า** = Net Revenue เทียบ Revenue Target ของเดือนนั้น **เกณฑ์รักษากำไร** = Contribution Profit หลังต้นทุนที่เกี่ยวข้อง ÷ Gross Reference Sales ราคาเต็ม ต้องไม่น้อยกว่า **10%** Ads อยู่ระดับวัน × กลุ่มสินค้า จึงไม่กระจาย Ads ลง SKU โดยไม่มีเกณฑ์จัดสรร และไม่บวก Reported Ads GMV เป็นยอดขายร้านซ้ำ

ML ใช้ Mart จาก Warehouse รอบที่รันบนเว็บ พร้อมแผนการตลาดสังเคราะห์ที่บันทึกแยกจาก ER1 ธุรกรรม Feature หนึ่งแถวแทนสัปดาห์ × กลุ่มสินค้า มีข้อมูลยอดขาย/Ads ย้อนหลังและแผนที่ทราบก่อนสัปดาห์เป้าหมาย เลือกโมเดลด้วย Validation ตามเวลา แล้วรายงาน WAPE บน Test ที่กันไว้ คะแนนอาจไม่ผ่านเกณฑ์และต้องแสดงตามจริง การปรับงบหรือส่วนลดในหน้า Scenario เป็นการลองเปลี่ยนตัวแปรของโมเดล **ไม่ใช่หลักฐานเชิงเหตุและผล** ว่าเพิ่มงบแล้วจะเพิ่มยอดขาย โมเดลนี้ยังไม่ทำนายกำไรหรือรับรองเกณฑ์ 10%; ตรวจต้นทุนจริงในภาพรวมธุรกิจประกอบการตัดสินใจ

## รันเองใน Google Colab

Colab ใช้พื้นที่ชั่วคราวของผู้เปิดเอง ไม่เชื่อม Neon Lab หรือเคลียร์ข้อมูลของผู้อื่น

1. [Pipeline Notebook](notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb) — สร้าง Source CSV ตรวจทีละชั้นข้อมูล รันข้อมูลตั้งต้นและข้อมูลเติมครบทุกชุด ทดสอบ Error แยก และมีตัวเลือกเคลียร์ผลใน Runtime ตอนท้าย
2. [ML Notebook](notebooks/TikTok_Shop_ML_Study.ipynb) — รัน Source ทั้ง 7 ชุดเข้า Warehouse เดียวกัน แล้วสร้าง Feature ฝึก/เทียบโมเดล ตรวจ WAPE และลอง Scenario จากโมเดลที่บันทึกไว้

เปิด Notebook จาก GitHub ใน Colab แล้วเลือก **Runtime → Run all**; โค้ดจะติดตั้ง dependencies ภายใน Runtime ผลตัวเลขขึ้นกับการรันจริงของ Runtime นั้น

## ตรวจสอบโค้ดและผลรัน

- [Source generator](pipeline/generate_classroom_source.py) · [ER1/ER2](schemas/) · [Workflow รันจริง](.github/workflows/classroom-live-batch.yml) · [Workflow ฝึก ML](.github/workflows/classroom-ml-train.yml)
- [กฎ KPI](sql/monthly_kpi_view.sql) · [Feature และการทดสอบโมเดล](pipeline/ml_weekly.py) · [CI ตรวจ 7 ชุด](pipeline/ci_classroom_source.py)

GitHub Actions เก็บหลักฐานแต่ละรอบไว้ตรวจสอบ แต่หน้าเว็บจะยึด Lab cycle และ Warehouse ที่ผ่าน Validation ล่าสุดเท่านั้น
