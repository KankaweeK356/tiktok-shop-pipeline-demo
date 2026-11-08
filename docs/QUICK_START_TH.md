# คู่มือ Demo แบบทีละขั้น — TikTok Shop Data Pipeline

[![เปิด Step-by-Step Demo](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/main/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb)

**แนะนำสำหรับนำเสนออาจารย์:** เปิด Step-by-Step Demo แล้วเลือก **Runtime → Run all เพียงครั้งเดียว** แต่ละ Stage จะรันอัตโนมัติและแสดง Output แยกใต้ Cell จากบนลงล่าง ไม่ต้องแก้ Code

**วิธีอ่านผล:** ก่อนแต่ละ Cell จะอธิบายว่า *กำลังทำอะไร / ดูตัวเลขอะไร / ทำไมสำคัญ* และใต้ Cell จะมีผลจริงจากการรัน พร้อมตัวอย่างข้อมูล 3–5 แถวและข้อความสรุปภาษาง่าย

**จำสามคำนี้:** ER1 คือโครงสร้าง **SQLite Database** สำหรับธุรกรรม, Data Lake คือพื้นที่เก็บ **ไฟล์ CSV/Parquet** ระหว่างทาง, ER2 คือโครงสร้าง **DuckDB Data Warehouse** สำหรับวิเคราะห์ยอดขาย ต้นทุน และกำไร ไม่ใช่ชื่อของชั้นข้อมูลเดียวกัน

| ลำดับ | ขั้นตอน | ผลลัพธ์ที่ต้องชี้ให้อาจารย์ดู |
|---|---|---|
| 00–01 | Setup + Source CSV | จำนวน Orders/Order Items, ข้อมูลตัวอย่าง |
| 02 | SQLite ER1 | จำนวน Records ใน Fact_Orders, Fact_Order_Items, Dim_SKU |
| 03–04 | Data Lake | Landing CSV → Raw Parquet → Standardized Parquet |
| 05 | DuckDB ER2 | จำนวน Fact, Dimension, Mart และตัวอย่าง |
| 06 | Functional/Lineage | ผลตรวจยอด, ข้อมูลต้นทางเทียบ Warehouse |
| 07–12 | Incremental Load | Source ใหม่/Order เดิมที่แก้ → ER1 → Lake → ER2 → ตรวจยอด |
| 13 | Replay Batch เดิม | จำนวนและยอดขาย **ไม่เพิ่มซ้ำ** |
| 14 | Error Injection + Recovery | เลือก Error แล้วดู Detect, Retry Stage, PASS |
| 15 | Full Test/KPI | Error 6 Cases, Latency, Throughput, ยอดขาย/กำไร |
| 16 | Google Drive (Optional) | บันทึก Snapshot หากเลือกใช้ |

**อย่าสับสนระหว่างสองคำนี้:** Incremental = **นำ Batch ใหม่เข้า** และทำให้ยอดเปลี่ยนจริง; Replay = **ส่ง Batch เดิมซ้ำ** ระบบต้องไม่สร้างข้อมูลซ้ำ

**กด Run all ซ้ำ:** ทำได้ทันทีและเริ่ม Demo ใหม่ครบเส้นทาง โดย Setup รีเซ็ตเฉพาะ `output/main` ใน Colab *ครั้งเดียวตอนเริ่ม* เท่านั้น ส่วน Run 2 เพิ่ม/อัปเดตในฐานข้อมูล Run 1 เดิม และ Replay ทดสอบว่า Batch เดิมไม่สร้างรายการซ้ำ ไม่ต้องลบ Source หรืออัปโหลด ZIP

**ข้อมูลที่สร้างอยู่ใน:** `output/main/er1.sqlite`, `output/main/lake/`, `output/main/er2.duckdb`, `output/main/reports/` ของ Colab Runtime ผู้รัน

---

# ทางเลือก: Quick Demo แบบรันอัตโนมัติ

[![เปิด Quick Demo บน Google Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/main/notebooks/TikTok_Shop_Quick_Demo.ipynb)

**สำหรับอาจารย์หรือผู้ที่เพิ่งทดลอง:** เปิดลิงก์ด้านบน → ไปที่ **Runtime → Run all** → ดูผลตามลำดับ ไม่ต้องดาวน์โหลด ZIP ไม่ต้องแก้ Code และไม่ต้องเชื่อม Google Drive

| หน้า Quick Demo | ทำอะไร | ผลลัพธ์ |
|---|---|---|
| **00 Setup** | ดึง CSV และ Code จาก GitHub | จำนวน Source Orders |
| **01 Load & Validate** | Run 1 → Run 2 → รันซ้ำ → Functional + Lineage | ยอดขายก่อน/หลัง, ไม่มีข้อมูลซ้ำ, ผลตรวจ |
| **02 Error Recovery** | จำลอง/แก้ Error 6 กรณีอัตโนมัติ | Error, ขั้นที่ Retry, PASS/FAIL |
| **03 KPI & Performance** | วัดเวลาประมวลผลและกำไร | ตาราง, กราฟ, รายงาน |
| **04 Google Drive** | ทางเลือก (ปิดไว้) | ไม่ขอสิทธิ์ Drive ถ้าไม่ติ๊ก |

**รันใหม่ทั้งหมด:** เลือก Runtime → Run all ซ้ำ — โปรแกรมรีเซ็ตเฉพาะผลทดลองใน Runtime ไม่แก้ Source ที่ GitHub

**หากต้องการแก้เงื่อนไขจำลอง Error หรือล้าง Snapshot Drive:** ใช้ [Detailed Notebook](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/main/notebooks/TikTok_Shop_Demo.ipynb)

---

## รายละเอียดสำหรับผู้ที่ต้องการตรวจทีละขั้น
# Detailed Demo (Advanced)

ใช้เวลาอ่านแค่ส่วนนี้ก็เริ่มทดลองได้ ไม่ต้องเปิดทุกไฟล์ใน Repository

## เปิดใช้งาน

[![เปิด Demo บน Google Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/main/notebooks/TikTok_Shop_Demo.ipynb)

1. คลิกปุ่ม **Open in Colab** ด้านบน
2. รันหัวข้อ **00 เตรียมโปรเจกต์** — ระบบดึง Code และข้อมูลจาก GitHub อัตโนมัติ ไม่ต้องอัปโหลด ZIP หรือกรอก URL
3. รันหัวข้อ **01 Run 1** — สร้างฐานข้อมูลและสรุปยอดตั้งต้น
4. รันหัวข้อ **02 Run 2** — เพิ่มข้อมูลใหม่ อัปเดตข้อมูลเดิม และตรวจว่ารันซ้ำแล้วยอดไม่เพิ่มซ้ำ
5. รันหัวข้อ **03–05** ตามต้องการ — ตรวจข้อมูล, Error/Recovery, Performance และผลธุรกิจ

ผลสรุปอยู่ใต้ Cell และไฟล์ละเอียดอยู่ใน `output/` ในแถบ Files ของ Colab (เป็นพื้นที่ชั่วคราวของผู้รันเอง)

## ถ้าจะทดลองใหม่

| ต้องการทำอะไร | ทำอย่างไร |
|---|---|
| ทดลอง Run 2 ซ้ำ | กดหัวข้อ 02 อีกครั้ง ระบบต้องไม่สร้างรายการเดิมซ้ำ |
| เริ่มตั้งแต่ Run 1 ใหม่ | ตั้ง `RESET_DEMO=True` ใน 00 → กด Run → เปลี่ยนเป็น `False` → เริ่ม 01 |
| ทดลอง Error ที่กำหนดเอง | ในหัวข้อ 04 เลือก `specific` และ Error Case |
| ทดสอบ Error ครบทุกกรณี | ในหัวข้อ 04 ใช้โหมด `all` หรือหัวข้อทดสอบครบ 6 กรณี |
| Runtime หลุดหรือปิด | เปิด Notebook ใหม่ รัน 00 แล้วรันขั้นที่ต้องการตามสถานะไฟล์ที่ยังอยู่; หากไฟล์หายให้เริ่ม 01 ใหม่ |

**หมายเหตุ:** ฟังก์ชัน Test ใช้พื้นที่แยกจาก Main Demo การทดลอง Error ไม่ควรเปลี่ยนยอดขายหลัก และข้อมูลใน Colab เป็นพื้นที่ชั่วคราว

## ถ้ามีปัญหา

- **หาไฟล์ไม่เจอ:** ตรวจ `REPO_URL` และดูว่า Repository มีโฟลเดอร์ `pipeline/`, `source/` อยู่ระดับบนสุด ไม่ใช่อยู่ในโฟลเดอร์ซ้อน
- **Run 2 ก่อน Run 1:** ต้องรัน 01 ให้สำเร็จก่อน
- **ติดตั้ง Library ไม่ได้:** ตรวจการเชื่อมต่ออินเทอร์เน็ตและลองรัน Setup ใหม่
- **ตรวจยอดไม่ผ่าน:** ดูรายงานใน `output/main/reports/` ก่อนรันขั้นถัดไป

**สถานะการทดสอบ:** [อ่านข้อจำกัดที่ตรวจยืนยันแล้ว](VALIDATION_STATUS.md)  
**ดูภาพรวมงาน:** [README หน้าแรก](../README.md)


## ถ้าต้องการให้ GitHub มีรายงานที่ตรวจแล้ว

เมื่อ Run 1, Run 2, Functional/Lineage, Error Tests ทั้ง 6 กรณี และ Performance/Business Results ผ่านจริงบน Colab:

1. ในหัวข้อ **05.3** ตั้ง `PREPARE_GITHUB_REPORTS=True` แล้วกดรัน
2. ถ้าระบบแจ้งว่ารายงานยังไม่ครบ ให้กลับไปรัน Section ที่ขาดก่อน (ระบบไม่แต่งตัวเลขขึ้นมาแทน)
3. ตั้ง `DOWNLOAD_GITHUB_REPORTS_ZIP=True` แล้วกดรันซ้ำ เพื่อดาวน์โหลด `github_report_upload.zip`
4. แตก ZIP จะเห็น `reports/` แล้วนำไปอัปโหลดขึ้น GitHub Repository เดิมและกด Commit changes
5. เปิด `reports/README.md` บน GitHub เพื่อตรวจว่าลิงก์รายงานใช้งานได้

**หมายเหตุ:** คนอื่นที่รัน Colab จะไม่ได้อัปโหลดผลกลับ GitHub ของเจ้าของโปรเจกต์อัตโนมัติ

## หากต้องการบันทึกผลบน Google Drive

เลือกหัวข้อ **05.4** ตั้ง `DRIVE_ACTION=save` แล้วกดรัน Colab จะขอให้เชื่อม Drive ของตัวเอง และบันทึกผลไว้ที่ `MyDrive/TikTok_Shop_Demo/snapshots/<เวลา>` โดยไม่เปลี่ยนข้อมูลบน GitHub

หากต้องการล้างผลที่บันทึกไว้ ให้ตั้ง `DRIVE_ACTION=clear` และพิมพ์ `CLEAR_TIKTOK_SHOP_DEMO` ที่ช่อง `CLEAR_CONFIRM` ก่อนกดรัน ระบบจะลบเฉพาะ Snapshot ที่ระบบสร้างในโฟลเดอร์ Demo นี้ **อย่าใช้กับโฟลเดอร์ Drive ที่มีไฟล์อื่นปะปน**

ถ้าไม่ต้องการใช้ Drive ปล่อย `DRIVE_ACTION=none` ได้เลย ไม่ต้องให้สิทธิ์ Drive
