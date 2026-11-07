# สถานะการทดสอบ (อัปเดต 7 พฤศจิกายน 2026)

เอกสารนี้แยก **สิ่งที่ตรวจแล้ว** ออกจาก **สิ่งที่ยังต้องรันบน Google Colab จริง** เพื่อไม่ให้เข้าใจว่า Demo ผ่านครบทั้งระบบก่อนทดสอบ

## สิ่งที่ตรวจแล้วในสภาพแวดล้อมพัฒนา

- ตรวจ ER 1 ได้ **25 ตาราง** และ ER 2 มี **12 องค์ประกอบ** (รวม Mart และ logical View)
- ตรวจ Python Syntax และโครงสร้าง Notebook
- ทดสอบการสร้างและรับข้อมูล Initial/Incremental ใน SQLite ของ ER 1
- ทดสอบตรรกะการแปลงข้อมูลและ Warehouse SQL ด้วย **ตัวแทน SQLite/Pandas** เนื่องจากเครื่องทดสอบไม่มี DuckDB/PyArrow และไม่สามารถติดตั้งผ่านอินเทอร์เน็ตได้ ผลนี้เป็น **Logic-level tests** ไม่ใช่การทดสอบ DuckDB/Parquet จริง
- ในการทดสอบด้วยตัวแทน: Run 1 มี 973 Paid Order Items และ Net Revenue 354,704.90 บาท; Run 2 มี 1,147 Paid Order Items และ Net Revenue 417,092.85 บาท; ผลตรวจ 20/20 และ 21/21 ผ่าน ตามลำดับ
- ชุด Error/Recovery ในสภาพแวดล้อมตัวแทนผ่าน 6/6 กรณี (5 กรณีจำลอง Failure และ 1 กรณี Batch ซ้ำ)

ตัวเลขข้างต้นเป็น **ผลจากข้อมูลจำลองและสภาพแวดล้อมทดสอบ** ไม่ใช่ยอดจาก TikTok จริง และไม่ใช่ผลวัด Performance ของ Google Colab

## สิ่งที่ยังต้องยืนยันบน Google Colab

1. สร้างและอ่าน Parquet จริงผ่าน `pyarrow` ได้
2. สร้างและโหลด Warehouse จริงผ่าน `duckdb` รวมถึง Monthly KPI View ได้
3. Reset → Run 1 → Run 2 ผ่านครบ และ Run 2 ซ้ำแล้วไม่เกิดข้อมูลซ้ำ
4. Functional Test, Lineage, Error/Recovery ผ่านใน Runtime จริง
5. Latency และ Throughput วัดจากการรันจริงบน Colab พร้อมเก็บเวลาและสภาพแวดล้อม

**เกณฑ์การประกาศว่า Demo พร้อมนำเสนอ:** ข้อ 1–5 ผ่านบน Colab จริง พร้อมรายงานผลจาก `output/` ไม่ใช่อ้างผลจากตัวแทนการทดสอบเท่านั้น

[กลับหน้าแรก](../README.md)


## การเผยแพร่ผลทดสอบลง GitHub

เพิ่มหัวข้อ 05.3 ใน Notebook เพื่อสร้าง ZIP ของรายงานจาก **ผลการรันจริงเท่านั้น** โดยต้องมี Checkpoint ครบ Run 1 / Run 2, Functional Checks ผ่าน, Error Recovery ผ่านครบทั้ง 6 กรณี, ผล Performance และ Business KPI ก่อน Export ได้

ปัจจุบันยังไม่ได้ยืนยัน End-to-End บน Colab จริง ดังนั้นไฟล์ `reports/README.md` ใน GitHub จะแสดงสถานะ *รอผลรันจริง* จนกว่าผู้ใช้จะรันและอัปโหลดไฟล์เอง

## การเก็บผลบน Google Drive

หัวข้อ 05.4 เพิ่ม Save/Clear Snapshots แบบ Optional ใช้ Drive ของผู้ทดลองแต่ละคน ไม่ส่งข้อมูลกลับ GitHub และไม่บังคับเชื่อม Drive โดยคำสั่ง Clear ต้องพิมพ์ `CLEAR_TIKTOK_SHOP_DEMO` ให้ตรงก่อนลบเฉพาะ Snapshots ของ Demo
