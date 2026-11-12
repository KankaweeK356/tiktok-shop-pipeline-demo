# สร้าง GitHub สำหรับ TikTok Shop Data Pipeline Demo

คู่มือนี้ใช้หน้าเว็บ GitHub อย่างเดียว **ไม่ต้องใช้คำสั่ง Git**

## 1. สร้าง Repository

1. สมัครหรือเข้าสู่ระบบที่ [GitHub](https://github.com/)
2. เปิด [สร้าง Repository ใหม่](https://github.com/new)
3. ตั้งชื่อ `tiktok-shop-pipeline-demo`
4. เลือก **Public** สำหรับชุดข้อมูลจำลอง เพื่อให้เปิดจาก Google Colab ได้สะดวก
5. **ไม่ต้องเลือก Add a README file** เพราะชุดไฟล์มี `README.md` อยู่แล้ว
6. กด **Create repository**

หากใช้ Private Repository จะต้องตั้งค่าวิธีให้ Colab เข้าถึง Repository เพิ่ม ไม่แนะนำสำหรับการเริ่มต้นครั้งแรก

## 2. อัปโหลดชุดไฟล์

1. ดาวน์โหลดไฟล์ `TikTok_Shop_GitHub_Ready_Reviewed.zip` แล้วเลือก **Extract All**
2. เปิดโฟลเดอร์ที่แตก ZIP จะเห็น `README.md`, `requirements.txt`, `pipeline/`, `source/`, `schemas/`, `notebooks/` และ `docs/`
3. เข้า Repository ที่สร้าง กด **uploading an existing file** หรือ **Add file → Upload files**
4. ลาก **ไฟล์และโฟลเดอร์ข้างใน** โฟลเดอร์ที่แตก ZIP ขึ้นไป ไม่ใช่ลาก ZIP ทั้งก้อน
5. ใส่ข้อความ Commit เช่น `Add pipeline demo files` แล้วกด **Commit changes**

หลังอัปโหลด หน้าแรก GitHub ควรเห็น `README.md`, `notebooks/`, `source/`, `pipeline/` และ `schemas/` อยู่ระดับเดียวกัน

## 3. ตั้งข้อความหน้า Repository ให้คนอ่านเข้าใจทันที

ที่หน้า Repository มองหาส่วน **About** แล้วกดไอคอนแก้ไข (รูปเฟืองหรือ Edit)

**Description (คัดลอกได้):**

> Demo Data Pipeline สำหรับ TikTok Shop ด้วยข้อมูลจำลอง: CSV → SQLite → Parquet → DuckDB พร้อม Initial/Incremental Load, Data Quality และ Error Recovery

**Topics (เพิ่มได้ตามต้องการ):** `data-engineering`, `etl`, `data-pipeline`, `data-warehouse`, `google-colab`, `duckdb`, `sqlite`, `parquet`, `python`

**Website:** เว้นว่างได้ก่อน หากยังไม่ได้มีเว็บโครงการ

ข้อความยาวทั้งหมดให้อ่านต่อใน `README.md` ซึ่ง GitHub จะแสดงบนหน้าแรกโดยอัตโนมัติ ไม่ต้องนำรายละเอียดทั้งหมดไปใส่ Description

## 4. เปิด Demo ใน Google Colab

1. เปิด [Google Colab](https://colab.research.google.com/)
2. เลือก **File → Open notebook → GitHub** แล้วค้นหาหรือวางลิงก์ Repository ที่เพิ่งสร้าง
3. เลือก `notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb`
4. เลือก **Runtime → Run all** เพื่อเตรียม Code และ Source จาก Repository ที่กำหนดไว้
5. กดปุ่ม **เริ่มรอบใหม่และรัน Run 1 · มกราคม** แล้วกด **เติมข้อมูลเดือนถัดไป** ทีละเดือนตามต้องการ

ผลของแต่ละรอบจะแสดงใน Notebook และเก็บใน `output/colab_classroom/` ภายใน Colab Runtime; กดปุ่มเคลียร์เมื่อต้องการลบผลทดลอง

## 5. ถ้าอยากอัปเดต README ภายหลัง

1. เข้า Repository แล้วคลิกไฟล์ `README.md`
2. กดไอคอน **Edit** (รูปดินสอ)
3. แก้ข้อความแล้วกด **Commit changes**

หรืออัปโหลด `README.md` เวอร์ชันใหม่ไปที่ตำแหน่งเดิม แล้ว Commit การเปลี่ยนแปลง โดยตรวจข้อความบนหน้าแรกอีกครั้ง

**ข้อควรระวัง:** ห้ามใส่ Password, Token, ข้อมูลลูกค้าจริง หรือไฟล์ผลลัพธ์ที่มีข้อมูลส่วนตัวลง Public Repository

อ่านเพิ่มเติม: [GitHub Docs — Create a repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository) · [GitHub Docs — Add files](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)

[กลับ README หน้าแรก](../README.md)


## ลิงก์เปิด Demo สำหรับผู้เข้าเยี่ยมชม

หลังอัปโหลดเสร็จ คนอื่นเปิด [Pipeline Notebook รุ่นปัจจุบันใน Colab](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb) ได้เลย. เลือก **Runtime → Run all** เพื่อเตรียมโปรเจกต์ จากนั้นกดปุ่มเริ่ม Run 1 และปุ่มเติมเดือนถัดไปบน Notebook.

ลิงก์โดยตรง: https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb

Notebook ตั้ง Repository และสาขาไว้แล้ว จึงดึง Code และ Source จาก GitHub อัตโนมัติเมื่อเตรียม Runtime; Colab ใช้ฐานข้อมูลแยกจาก Neon และข้อมูล Dashboard
