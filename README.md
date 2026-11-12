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

ตัวสร้าง Source ใช้ seed เดียวกันทุกครั้งและเตรียมข้อมูล **10 ชุดรายเดือน มกราคม–ตุลาคม 2569**. `initial` คือ Run 1 เดือนมกราคม; `incremental_01` ถึง `incremental_09` เติมเดือนก.พ.–ต.ค. ทีละเดือน. ทุก ZIP มี CSV 21 ตารางและ manifest ตาม ER1 เหมือนกัน; Master/Reference เริ่มต้นอยู่ใน Run 1 ส่วนรายการธุรกิจและเป้าหมายรายเดือนเข้าตามเดือน. ER1 มี 25 ตาราง โดย 4 ตารางสร้างจากการประมวลผลของ Pipeline ไม่ได้ส่งเป็น Source CSV. Source แยกจาก Neon และจากผล Data Lake/Warehouse.

**จำนวนข้อมูลไม่ได้ล็อกเป็น 800/900 หรือเพิ่มครั้งละ 100 ออเดอร์:** ตัวเลขดังกล่าวมาจากชุด Source รุ่นเก่าใน `source/initial` และ `source/incremental`. ตัวสร้างชุดปัจจุบันแบ่งธุรกรรมตามเดือนมกราคม–ตุลาคม; Run 1 คือมกราคม และการเติมแต่ละครั้งคือเดือนถัดไป จำนวนเพิ่มจริงเปลี่ยนไปตามข้อมูลของเดือนนั้น และอ่านจาก manifest/ผลรัน ไม่ใช่ตัวเลขกำหนดล่วงหน้า. ชุด 800 ออเดอร์เก่าถูกใช้เป็นข้อมูลของเดือนตุลาคมในชุดรายเดือน ส่วนชุดพฤศจิกายน 100 ออเดอร์ไม่ได้เป็น Run 2 ของ Flow ปัจจุบัน.\n\nหน้า Test Pipeline แสดง Source เดือนถัดไป พร้อม ZIP ให้ดาวน์โหลดหรืออัปโหลด ZIP ของเดือนนั้น. ถ้าไม่อัปโหลด ระบบใช้ Source ที่เตรียมไว้. ก่อน Run จะตรวจชื่อเดือน, 21 ตาราง, คอลัมน์, Primary Key และทดลองนำเข้าใน ER1 SQLite ชั่วคราวเพื่อตรวจชนิดข้อมูล/ความสัมพันธ์; มีเพียง Source ที่ผ่านการตรวจเท่านั้นที่ถึงขั้น sync เข้า Neon. ผู้ชมกด **Run 1** และ **เติมข้อมูลใหม่** โดยไม่ต้องเลือกเลขชุดเอง. เมื่อเติมถึงตุลาคมจะแจ้งว่าไม่มี Source เดือนถัดไป. จำนวนออเดอร์ก่อน–หลังและยอดขายมาจากผลรันจริง. หาก Run ไม่ผ่านให้ดูสาเหตุและขั้นที่ติด แล้วกดปุ่มเดิมเพื่อ Retry; Error Lab เป็นชุดทดสอบแยกจากข้อมูลปกติ.

Run และการเคลียร์ใช้ Lab ร่วมกันสำหรับทุกคนที่เปิดลิงก์. หน้าทดสอบจะแสดงเมื่อมีงานกำลังทำและอยู่ขั้นไหน แล้วอัปเดตสถานะให้อัตโนมัติ; ไม่ต้องมีบัญชี GitHub ของผู้ชม. ปุ่ม Run เรียก GitHub Actions ของโครงการผ่านการเชื่อมต่อฝั่งเว็บ จึงต้องตั้งค่า `CLASSROOM_GITHUB_TOKEN`, `CLASSROOM_LAB_NEON_URL` และ `CLASSROOM_LAB_WRITER_URL` ใน Vercel ให้ครบ ผู้ชมไม่ต้องกรอกรหัสเหล่านี้.

ปุ่ม **เคลียร์ข้อมูล Lab** ลบข้อมูลธุรกิจใน Neon ของรอบปัจจุบันและเริ่มรอบใหม่ ข้อมูล Warehouse/ML รอบเก่าไม่ถูกนำมาแสดงเป็นข้อมูลปัจจุบัน ไฟล์ Source ไม่ถูกลบ Log GitHub เก่าเก็บไว้ตรวจย้อนหลัง หากเว็บยังแสดงรอบข้อมูลที่สร้างด้วยระบบสองชุดเดิม ให้เคลียร์ Lab หลังตรวจว่าไม่มีงานกำลังรัน เพื่อเริ่มชุด 10 Source รายเดือนนี้

> Neon เก็บ ER1 Database จริง ส่วน Data Lake เป็นไฟล์ Parquet และ Warehouse เป็น DuckDB ใน GitHub Actions Artifact จึงไม่เห็นตาราง Warehouse ใน Neon Console โดยตรง. แท็บ Neon ในหน้า Test Pipeline อ่านรายชื่อตาราง จำนวนแถว คอลัมน์ และตัวอย่างข้อมูลจริงจาก Lab ให้ดูได้ในเว็บ โดยไม่ต้องเข้า Neon Console.

### KPI และ ML

**ยอดขายเทียบเป้า** = Net Revenue เทียบ Revenue Target ของเดือนนั้น **เกณฑ์รักษากำไร** = Contribution Profit หลังต้นทุนที่เกี่ยวข้อง ÷ Gross Reference Sales ราคาเต็ม ต้องไม่น้อยกว่า **10%** Ads อยู่ระดับวัน × กลุ่มสินค้า จึงไม่กระจาย Ads ลง SKU โดยไม่มีเกณฑ์จัดสรร และไม่บวก Reported Ads GMV เป็นยอดขายร้านซ้ำ

ML ใช้ Mart จาก Warehouse รอบที่รันบนเว็บ พร้อมแผนการตลาดสังเคราะห์ที่บันทึกแยกจาก ER1. Feature หนึ่งแถวแทนสัปดาห์ × กลุ่มสินค้า และใช้ยอดขาย/Ads ย้อนหลังกับแผนที่ทราบก่อนสัปดาห์เป้าหมาย. หน้า ML แสดงจำนวนสัปดาห์ข้อมูลที่ครบและใช้ได้; Train จะเปิดเมื่อมีอย่างน้อย **16 สัปดาห์** เพื่อแบ่งช่วง Train/Validation/Test ตามเวลาจริง ไม่ได้นับจำนวนเดือนแบบคร่าว ๆ. ก่อนถึงเกณฑ์จะยังไม่สร้างคะแนน WAPE หรือคำทำนาย. ผลประเมินเป็นข้อมูลจำลองและอาจไม่ผ่านเกณฑ์. การปรับงบหรือส่วนลดในหน้า Scenario เป็นการลองเปลี่ยนตัวแปรของโมเดล **ไม่ใช่หลักฐานเชิงเหตุและผล** ว่าเพิ่มงบแล้วจะเพิ่มยอดขาย. โมเดลนี้ยังไม่ทำนายกำไรหรือรับรองเกณฑ์ 10%; ตรวจต้นทุนจริงในภาพรวมธุรกิจประกอบการตัดสินใจ.

## รันเองใน Google Colab

Colab ใช้พื้นที่ชั่วคราวของผู้เปิดเอง ไม่เชื่อม Neon Lab หรือเคลียร์ข้อมูลของผู้อื่น

1. [Pipeline Notebook](notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb) — สำรองสำหรับ Colab: กด **Runtime → Run all** เพื่อเตรียมโปรเจกต์ แล้วกดปุ่ม **เริ่มรอบใหม่และรัน Run 1 · มกราคม**; ปุ่ม **เติมข้อมูลเดือนถัดไป** เพิ่มครั้งละหนึ่งเดือนถึงตุลาคม. แต่ละครั้งรันครบ Database → Data Lake → Warehouse → Validation และแสดงสถานะและจำนวนก่อน–หลัง พร้อมตาราง/จำนวนแถวและตัวอย่างจริงแยก Database, Data Lake (Landing/Raw/Standardized) และ Warehouse. ปุ่ม Error Test แยกจาก Pipeline ปกติ.
2. [ML Notebook](notebooks/TikTok_Shop_ML_Study.ipynb) — สร้าง Feature จาก Warehouse, แบ่ง Train/Validation/Test ตามเวลา และประเมิน WAPE. Notebook แสดงจำนวนสัปดาห์ Feature ที่ครบจริงและฝึกเมื่อพร้อมอย่างน้อย 16 สัปดาห์ (Train 6 + Validation 2 รอบ รอบละ 3 + Test 4); ไม่ถือว่า 1 เดือนเท่ากับ 1 ตัวอย่าง. ผลใน Colab เป็นของ Runtime นั้นและไม่ส่งขึ้น Dashboard หรือ Neon.

เปิด Pipeline Notebook จาก GitHub ใน Colab แล้วเลือก **Runtime → Run all** เพื่อเตรียม Code/Source (ยังไม่รันข้อมูล) จากนั้นกดปุ่มบน Notebook ตามลำดับ. **เริ่มรอบใหม่** จะล้างผลเดิมเฉพาะ Colab และรันมกราคม; **เติมเดือนถัดไป** เพิ่มทีละเดือน; **เคลียร์ผลทดลองใน Colab** ล้างผล Pipeline และ Error Lab ใน Runtime โดยคง Source ไว้. เมื่อใช้ Runtime ใหม่ ให้กดเริ่มรอบใหม่. เวลาประมวลผลขึ้นกับ Runtime ที่ใช้.

## ตรวจสอบโค้ดและผลรัน

- [Source generator](pipeline/generate_classroom_source.py) · [ER1/ER2](schemas/) · [Workflow รันจริง](.github/workflows/classroom-live-batch.yml) · [Workflow ฝึก ML](.github/workflows/classroom-ml-train.yml)
- [กฎ KPI](sql/monthly_kpi_view.sql) · [Feature และการทดสอบโมเดล](pipeline/ml_weekly.py) · [CI ตรวจ 10 ชุด](pipeline/ci_classroom_source.py) · [Workflow เผยแพร่ ZIP รายเดือน](.github/workflows/publish-classroom-source.yml)

GitHub Actions เก็บหลักฐานแต่ละรอบไว้ตรวจสอบ แต่หน้าเว็บจะยึด Lab cycle และ Warehouse ที่ผ่าน Validation ล่าสุดเท่านั้น
