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

ตัวสร้าง Source ใช้ seed เดียวกันทุกครั้งและส่งออก CSV **7 ชุด** ภายใต้ `output/classroom_source/` ใน GitHub Worker. `initial` คือ Run 1 และมีข้อมูล **เดือนมกราคม 2569 เดือนเดียว**. `incremental_01` ถึง `incremental_06` เติมเดือน ก.พ.–ก.ค. 2569 ทีละเดือน. ทุกชุดมี CSV ครบ 21 ตาราง Source ตาม ER1; Master/Reference เริ่มต้นอยู่ใน Run 1 ส่วนรายการธุรกิจและเป้าหมายรายเดือนจะเข้าตามเดือน. ER1 มี 25 ตาราง โดย 4 ตารางสร้างจากการประมวลผลของ Pipeline ไม่ได้ส่งเป็น Source CSV. Source แยกจาก Neon และจากผล Data Lake/Warehouse.

บนเว็บผู้ชมเห็นเพียง **Run 1** และปุ่ม **เติมข้อมูลใหม่** ไม่ต้องเลือกลำดับชุดเอง. ระบบเลือก Source เดือนถัดไปให้อัตโนมัติ; เมื่อครบ ก.ค. 2569 จะแจ้งว่าไม่มีข้อมูลใหม่. จำนวนออเดอร์ก่อน–หลังและยอดขายมาจากผลรันจริง ไม่แสดงตัวเลขตั้งต้นแบบล็อกไว้. หากรันปกติไม่ผ่าน ให้ดูสาเหตุและขั้นที่ติด แล้วกดปุ่มเดิมเพื่อ Retry; Error Lab เป็นชุดทดลองปัญหาที่แยกจากข้อมูลปกติ.

Run และการเคลียร์ใช้ Lab ร่วมกันสำหรับทุกคนที่เปิดลิงก์. หน้าทดสอบจะแสดงเมื่อมีงานกำลังทำและอยู่ขั้นไหน แล้วอัปเดตสถานะให้อัตโนมัติ; ไม่ต้องมีบัญชี GitHub ของผู้ชม. ปุ่ม Run เรียก GitHub Actions ของโครงการผ่านการเชื่อมต่อฝั่งเว็บ จึงต้องตั้งค่า `CLASSROOM_GITHUB_TOKEN`, `CLASSROOM_LAB_NEON_URL` และ `CLASSROOM_LAB_WRITER_URL` ใน Vercel ให้ครบ ผู้ชมไม่ต้องกรอกรหัสเหล่านี้.

ปุ่ม **เคลียร์ข้อมูล Lab** ลบข้อมูลธุรกิจใน Neon ของรอบปัจจุบันและเริ่มรอบใหม่ ข้อมูล Warehouse/ML รอบเก่าไม่ถูกนำมาแสดงเป็นข้อมูลปัจจุบัน ไฟล์ Source ไม่ถูกลบ Log GitHub เก่าเก็บไว้ตรวจย้อนหลัง หากเว็บยังแสดงรอบข้อมูลที่สร้างด้วยระบบสองชุดเดิม ให้เคลียร์ Lab หลังตรวจว่าไม่มีงานกำลังรัน เพื่อเริ่มชุด 7 Source รุ่นใหม่นี้

> Neon เก็บ ER1 Database จริง ส่วน Data Lake เป็นไฟล์ Parquet และ Warehouse เป็น DuckDB ใน GitHub Actions Artifact จึงไม่เห็นตาราง Warehouse ใน Neon Console โดยตรง. แท็บ Neon ในหน้า Test Pipeline อ่านรายชื่อตาราง จำนวนแถว คอลัมน์ และตัวอย่างข้อมูลจริงจาก Lab ให้ดูได้ในเว็บ โดยไม่ต้องเข้า Neon Console.

### KPI และ ML

**ยอดขายเทียบเป้า** = Net Revenue เทียบ Revenue Target ของเดือนนั้น **เกณฑ์รักษากำไร** = Contribution Profit หลังต้นทุนที่เกี่ยวข้อง ÷ Gross Reference Sales ราคาเต็ม ต้องไม่น้อยกว่า **10%** Ads อยู่ระดับวัน × กลุ่มสินค้า จึงไม่กระจาย Ads ลง SKU โดยไม่มีเกณฑ์จัดสรร และไม่บวก Reported Ads GMV เป็นยอดขายร้านซ้ำ

ML ใช้ Mart จาก Warehouse รอบที่รันบนเว็บ พร้อมแผนการตลาดสังเคราะห์ที่บันทึกแยกจาก ER1 ธุรกรรม Feature หนึ่งแถวแทนสัปดาห์ × กลุ่มสินค้า มีข้อมูลยอดขาย/Ads ย้อนหลังและแผนที่ทราบก่อนสัปดาห์เป้าหมาย. หน้า ML แสดงรายการ Feature ตั้งแต่เริ่ม แต่จะเปิด Train เมื่อ Warehouse สะสมข้อมูลอย่างน้อย 5 เดือน เพื่อให้แบ่ง Train/Validation/Test ตามเวลาได้; ก่อนถึงจุดนั้นจะยังไม่สร้างคะแนน WAPE หรือคำทำนาย. ผลประเมินเป็นข้อมูลจำลองและอาจไม่ผ่านเกณฑ์. การปรับงบหรือส่วนลดในหน้า Scenario เป็นการลองเปลี่ยนตัวแปรของโมเดล **ไม่ใช่หลักฐานเชิงเหตุและผล** ว่าเพิ่มงบแล้วจะเพิ่มยอดขาย. โมเดลนี้ยังไม่ทำนายกำไรหรือรับรองเกณฑ์ 10%; ตรวจต้นทุนจริงในภาพรวมธุรกิจประกอบการตัดสินใจ.

## รันเองใน Google Colab

Colab ใช้พื้นที่ชั่วคราวของผู้เปิดเอง ไม่เชื่อม Neon Lab หรือเคลียร์ข้อมูลของผู้อื่น

1. [Pipeline Notebook](notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb) — Colab สำรองแบบ **Run all**: สร้าง Source CSV จาก GitHub, ตรวจโครงสร้าง 21 ตาราง, รันเดือนมกราคมเป็นชุดแรกและเติมเดือนถัดไปทีละชุดผ่าน Database → Data Lake → Warehouse, สรุปผลและทดสอบ Error แยก. เคลียร์ท้ายงานจะลบเฉพาะผลใน Colab Runtime.
2. [ML Notebook](notebooks/TikTok_Shop_ML_Study.ipynb) — ทางเลือกสำหรับดูรายละเอียด ML โดยเฉพาะ: สร้าง Feature จาก Warehouse, แบ่ง Train/Validation/Test ตามเวลา, เปรียบเทียบ WAPE และทดลอง Scenario. ผลใน Colab เป็นของ Runtime นั้นและไม่ส่งขึ้น Dashboard หรือ Neon ของเว็บ.

เปิด Notebook จาก GitHub ใน Colab แล้วเลือก **Runtime → Run all**; โค้ดจะติดตั้ง dependencies ภายใน Runtime ผลตัวเลขขึ้นกับการรันจริงของ Runtime นั้น

## ตรวจสอบโค้ดและผลรัน

- [Source generator](pipeline/generate_classroom_source.py) · [ER1/ER2](schemas/) · [Workflow รันจริง](.github/workflows/classroom-live-batch.yml) · [Workflow ฝึก ML](.github/workflows/classroom-ml-train.yml)
- [กฎ KPI](sql/monthly_kpi_view.sql) · [Feature และการทดสอบโมเดล](pipeline/ml_weekly.py) · [CI ตรวจ 7 ชุด](pipeline/ci_classroom_source.py)

GitHub Actions เก็บหลักฐานแต่ละรอบไว้ตรวจสอบ แต่หน้าเว็บจะยึด Lab cycle และ Warehouse ที่ผ่าน Validation ล่าสุดเท่านั้น
