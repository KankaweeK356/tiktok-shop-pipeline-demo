# ผลตรวจชุดแก้ไข TikTok Shop Pipeline (7 พฤศจิกายน 2026)

## สาเหตุ Error และสิ่งที่แก้

1. **PyArrow ArrowInvalid / `Voucher_Active`:** เดิมใช้ `True` ปนกับ `1` ที่อ่านจาก SQLite จึงแก้ให้ค่า Flag ทั้งหมดเป็น Boolean ก่อนเขียน Standardized Parquet
2. **DuckDB `Decimal` + Python `float`:** เดิม Functional Validation ใช้ `profit + 0.00001` จึงเกิด TypeError; เปลี่ยนเป็นการเปรียบเทียบ `Decimal` ด้วยกันทั้งคู่
3. **Incremental เลื่อนยอดผิดเดือน:** เดิมเลือก Order ตุลาคม 24 รายการแรกมาเปลี่ยนสถานะ โดยอาจมี Order จ่ายแล้วปนอยู่; แก้ให้เลือกเฉพาะ Order สถานะ `Pending` → `Paid` และสร้าง Source CSV ทั้งสอง Batch ใหม่
4. **ไฟล์ GitHub ไม่ครบ:** เพิ่มการเช็ก Source CSV ที่จำเป็นต่อ Batch และ Notebook Setup ตรวจไฟล์หลักก่อน Import พร้อม Git pull เมื่อนำ Code รุ่นใหม่ขึ้น GitHub
5. **ป้องกัน Error ย้อนกลับ:** เพิ่ม Regression Tests, การตรวจว่า October Net Revenue ไม่ถูกย้ายไป November และ GitHub Actions ที่รัน DuckDB/PyArrow จริง

## ผลที่ตรวจผ่านในเครื่องนี้

เครื่องทดสอบมี SQLite/Pandas แต่ **ไม่มี DuckDB และ PyArrow ที่ติดตั้งได้** จึงใช้ SQLite เป็นตัวแทน SQL และ Pickle เป็นตัวแทน Parquet สำหรับทดสอบ Logic เท่านั้น ไม่ใช่ผล End-to-End ของ Engine จริง

| การทดสอบด้วยตัวแทน | ผล |
|---|---|
| Pytest รวม Unit/Regression/Workflow | 12 ผ่าน |
| Run 1 Initial | SUCCESS: 973 Paid Order Items, Net Revenue 354,704.90 บาท |
| Run 2 Incremental | SUCCESS: 1,147 Paid Order Items, Net Revenue 417,092.85 บาท |
| Functional Reconciliation | Run 1 = 20/20, Run 2 = 21/21, Final = 21/21 |
| Idempotency | รัน Run 2 ซ้ำแล้วจำนวนรายการและยอดไม่เปลี่ยน |
| Error Recovery | E01, E02, T01, T02, L01, L02 ผ่าน 6/6 |
| Lineage | ติดตามตัวอย่าง 6 Order Items ถึง Fact/Mart/KPI ได้ |
| Reports Export | สร้างชุดรายงานหลังทดสอบครบได้ |
| Save/Clear Drive Logic | Tests ผ่านในพื้นที่ทดสอบแยก ไม่ได้แตะ Drive ของผู้ใช้ |

**ผล Latency/Throughput ในเครื่องทดสอบนี้ไม่ใช่ผล Performance ของ DuckDB/PyArrow หรือ Google Colab** จึงไม่นำตัวเลขดังกล่าวไปอ้างเป็น Benchmark จริง

## สิ่งที่ต้องยืนยันด้วย Engine จริง

ใน Repository มี `.github/workflows/pipeline-ci.yml` ซึ่งเมื่อ Commit ไปที่สาขา `main` จะติดตั้ง DuckDB และ PyArrow จริงแล้วทดสอบ Pipeline ครบสายการทำงานโดยอัตโนมัติ เปิดแท็บ **Actions** เพื่อดูสถานะและ Error Log หากไม่ผ่าน ทั้งนี้จนกว่าจะเห็น CI ผ่าน ยังไม่ควรประกาศว่า End-to-End ผ่านแล้ว

## วิธีใช้ชุดไฟล์นี้

แตก ZIP ชุดเต็ม → อัปโหลดไฟล์และโฟลเดอร์ภายในให้ตรงโครงสร้างที่หน้า Repository (`pipeline/` และ `source/` ต้องอยู่ที่ Root) → Commit changes → เปิด Actions ตรวจผลจริง → เปิด Notebook ผ่านปุ่ม Open in Colab → ใช้ Runtime ใหม่และตั้ง `RESET_DEMO=True` ใน Section 00 หนึ่งครั้งก่อนรัน Section 01–05
