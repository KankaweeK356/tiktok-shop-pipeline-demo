# TikTok Shop Fashion Intelligence — Classroom Demo

เว็บและชุดโค้ดสาธิตการนำข้อมูล **ร้านเสื้อผ้าจำลอง** ผ่าน Data Pipeline ครบวงจร ตั้งแต่ไฟล์ Source → ฐานข้อมูล → Data Lake → Data Warehouse → Dashboard พร้อมการพยากรณ์ยอดขาย และการเปรียบเทียบโมเดล ML กับวิธีมาตรฐาน ประกอบวิชา MADT8102 บทที่ 7 (MLOps & Feature Stores)

> **ข้อมูลทั้งหมดเป็นข้อมูลสังเคราะห์เพื่อการศึกษา ไม่ใช่ข้อมูลจริงของ TikTok หรือร้านค้าใด ๆ**

| ลิงก์ | รายละเอียด |
| :--- | :--- |
| [เปิดเว็บ Demo (Production)](https://tiktok-shop-mlops-dashboard.vercel.app/) | ระบบที่ใช้งานจริง ข้อมูลอยู่บน Neon และ Vercel |
| [บริบทและสถาปัตยกรรมทั้งระบบ](docs/PROJECT_CONTEXT_TH.md) | **เริ่มอ่านที่นี่** ถ้าอยากเข้าใจทั้งแอป |
| [Colab: Pipeline ทีละเดือน](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/claude/nice-ptolemy-gpmkm2/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb) | ทดลองรัน Pipeline เองในเครื่องของผู้เรียน |
| [Colab: ML Study](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/claude/nice-ptolemy-gpmkm2/notebooks/TikTok_Shop_ML_Study.ipynb) | ศึกษา Feature และโมเดลพยากรณ์จาก Warehouse |

---

## 1. แอปนี้ทำอะไร

1. **นำข้อมูลเข้า 10 เดือน** (มกราคม–ตุลาคม 2569) ทีละเดือน เดือนละ 1 ZIP ที่มี CSV 21 ตาราง โดยตรวจ Hash ของไฟล์กับ Source Lock ที่อนุมัติไว้
2. **ผ่าน 5 ขั้นตอน** แล้ว *Publish* เป็น Warehouse ที่ Business Dashboard ใช้ได้ ถ้าข้อมูลไม่ผ่านการตรวจคุณภาพ (DQ) ระบบจะหยุดก่อน Publish
3. **แก้ข้อมูลที่ผิดอย่างตรวจสอบย้อนหลังได้** เช่น เดือนมีนาคมมีรหัสสินค้า (SKU) ที่ไม่มีใน Master ผู้ใช้เลือกค่าที่ถูกต้องเอง ระบบบันทึกผู้แก้ เหตุผล และหลักฐาน แล้วตรวจซ้ำก่อนรันต่อ
4. **พยากรณ์ยอดขายและวางแผน** ตั้งแต่เดือนมิถุนายน ต้องสร้างและ Seal Official Forecast ของเดือนนั้นก่อนจึงรันเดือนนั้นได้
5. **เปรียบเทียบ ML กับ Baseline** (Champion–Challenger) โดย ML เป็นเพียงข้อมูลประกอบการตัดสินใจ **ไม่เปลี่ยน Official Forecast อัตโนมัติ**

## 2. ภาพรวมสถาปัตยกรรม

```
Source ZIP (10 เดือน · 21 CSV · ตรวจ SHA-256 กับ Source Lock)
   │ ① Source → Database
   ▼
ER1 บน Neon PostgreSQL (ฐานข้อมูลปฏิบัติการ)
   │ ② Database → Data Lake
   ▼
Data Lake (Parquet บน Neon Object Storage: Landing / Raw / Standardized)
   │ ③ Standardize + ตรวจคุณภาพ   ④ Lake → Warehouse
   ▼
ER2 / DuckDB Warehouse (Fact · Dim · Mart)
   │ ⑤ Validate (กระทบยอด ER1 ↔ ER2)  →  Publish Snapshot
   ▼
Dashboard (Vercel): Business Owner · Data Operations
```

- **เว็บ + API:** Vercel (หน้าเว็บ static, API แบบ JavaScript, Worker แบบ Python ประมวลผล ETL)
- **ฐานข้อมูล:** Neon PostgreSQL (ER1, ตารางควบคุม Run/DQ/Forecast)
- **ไฟล์ Data Lake และหลักฐาน ML:** Neon Object Storage (S3-compatible)
- **ผลลัพธ์ในรอบรัน:** เก็บเป็นหลักฐานต่อ Run เปิดดูย้อนหลังได้

## 3. ห้าขั้นตอนของ Pipeline

| ขั้นตอน | เข้า (Input) | ทำอะไร | ออก (Output) |
| :--- | :--- | :--- | :--- |
| **1. Source → Database** | ZIP รายเดือน (CSV 21 ไฟล์) | ตรวจ Hash/โครงสร้างไฟล์ ตรวจ Schema และ Foreign Key แล้วเขียนลง ER1 | ตารางใน ER1 หรือ DQ Issue ถ้าไม่ผ่าน |
| **2. Database → Data Lake** | ตาราง ER1 | สกัดข้อมูลของเดือนนั้นเป็น Raw Parquet | ไฟล์ Parquet ชั้น Raw |
| **3. Standardize** | Raw Parquet | จัดมาตรฐานชนิดข้อมูล วันที่ สถานะ | ไฟล์ Parquet ชั้น Standardized |
| **4. Lake → Warehouse** | Standardized Parquet | โหลดเข้า Star Schema และสร้าง Mart | DuckDB Warehouse |
| **5. Validate** | ER1 และ ER2 | กระทบยอดจำนวนรายการและยอดขายสุทธิ | หลักฐานการตรวจ → Publish Snapshot |

**Pipeline สำเร็จ ≠ ผลทางธุรกิจผ่าน** และข้อมูลที่อยู่ระหว่างประมวลผลหรือถูกบล็อกจะไม่ถูกนับเป็นข้อมูลที่ Publish แล้ว

## 4. หน้าจอบนเว็บ

| เมนู | ผู้ใช้ | ใช้ทำอะไร |
| :--- | :--- | :--- |
| ภาพรวมธุรกิจ | เจ้าของร้าน (Business Owner) | ดู KPI ยอดขาย กำไร และการแยกตามกลุ่มสินค้า จากเดือนที่ Publish แล้ว |
| ทดสอบการนำเข้าข้อมูล | ผู้ดูแลข้อมูล (Data Operations) | รัน Pipeline รายเดือน ดู **Data Operations Overview** (Published N/10, Next Action, สถานะ 5 ขั้น, DQ, Warehouse, ML) และแก้ DQ ที่ Review & Fix |
| คาดการณ์และวางแผน | ผู้วางแผน | สร้างและ Seal Official Forecast จัดทำแผน ดูผล ML ของเดือนนั้น |
| คาดการณ์เทียบผลจริง | ผู้วางแผน | เทียบ Forecast กับยอดจริงหลัง Publish และดู Champion–Challenger Monitoring |

## 5. การเรียนรู้ของเครื่อง (ML)

- Official Forecast ใช้ **Baseline** (ค่าที่ดีกว่าระหว่างค่าเฉลี่ย 3 เดือนล่าสุดกับ naive)
- **Ridge Regression** เป็น Challenger ฝึกจาก Feature Store แบบ Point-in-time (ไม่ใช้ข้อมูลอนาคต) และตรวจแบบ Walk-forward
- ผลเปรียบเทียบสะสมแสดงระดับหลักฐาน: น้อยกว่า 3 เดือน = *Insufficient*, 3–5 = *Preliminary*, ตั้งแต่ 6 = *Adequate*
- ระบบจะ **แนะนำให้ทบทวน** เมื่อ ML ชนะ Baseline ครบเกณฑ์ที่กำหนด แต่ **ไม่สลับ Champion และไม่สั่ง Retrain อัตโนมัติ** ผู้ตัดสินใจคือคน
- ในข้อมูลสาธิตที่มี ML ยังไม่ชนะ Baseline อย่างชัดเจน ซึ่งรายงานไว้ตามจริง

รายละเอียดและหลักฐานอยู่ที่ [docs/mlops_evidence](docs/mlops_evidence/README_TH.md)

## 6. รันใน Google Colab

Colab รันบนเครื่อง (Runtime) ของผู้เปิดเอง ใช้ SQLite + Parquet + DuckDB **ไม่เชื่อมต่อ Neon** และผลใน Colab **ไม่ปรากฏบนเว็บ**

| Notebook | ใช้ทำอะไร |
| :--- | :--- |
| [`TikTok_Shop_Step_by_Step_Demo`](notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb) | **ตัวหลัก** รัน Run 1 (ม.ค.) แล้วเติมทีละเดือน พร้อมทดสอบ Error 6 กรณี |
| [`TikTok_Shop_ML_Study`](notebooks/TikTok_Shop_ML_Study.ipynb) | สร้าง Feature จาก Warehouse และเปรียบเทียบโมเดล (ต้องมีประวัติอย่างน้อย 16 สัปดาห์) |
| `TikTok_Shop_Quick_Demo`, `TikTok_Shop_Demo` | รุ่นเก่า เก็บไว้อ้างอิง |

กด **Runtime → Run all** เพื่อเตรียมเครื่องมือ แล้วใช้ปุ่มในโน้ตบุ๊ก ตัวแปร `REPO_REF` ที่เซลล์แรกคือ branch ที่ Colab ดึงโค้ดมา

## 7. การทดสอบ

```bash
node --test tests/js/*.test.mjs        # ชุดทดสอบฝั่งหน้าเว็บ/API (64 กรณี)
python -m pytest tests -q              # ชุดทดสอบ Python
```

- ผลรอบล่าสุดและเหตุผลของเทสเก่าที่ล้มอยู่ก่อนแล้ว: [V4_TEST_RESULTS_TH.md](docs/mlops_evidence/V4_TEST_RESULTS_TH.md)
- ชุดทดสอบการกู้คืน DQ ต้องใช้ฐานข้อมูล PostgreSQL ชั่วคราวในเครื่อง ดู [DQ_RECOVERY_RUNBOOK_TH.md](docs/DQ_RECOVERY_RUNBOOK_TH.md)

## 8. เอกสารเพิ่มเติม

- [บริบทและสถาปัตยกรรมทั้งระบบ](docs/PROJECT_CONTEXT_TH.md)
- [คู่มือเริ่มต้นด่วน](docs/QUICK_START_TH.md) · [บทพูด Demo สำหรับอาจารย์](docs/DEMO_SCRIPT_FOR_TEACHER_TH.md)
- [Neon Pipeline Architecture](docs/NEON_CLASSROOM_PIPELINE_ARCHITECTURE_TH.md) · [การกู้คืนเมื่อ DQ ไม่ผ่าน](docs/DQ_RECOVERY_RUNBOOK_TH.md)
- [Feature Store](docs/FEATURE_STORE_IMPLEMENTATION_TH.md) · [หลักฐาน MLOps และ Champion–Challenger](docs/mlops_evidence/README_TH.md)
- [Data Operations Dashboard](docs/data_operations/DATA_OPERATIONS_TH.md)
- พจนานุกรมข้อมูล: [ER1](docs/ER1_Data_Dictionary.csv) · [ER2](docs/ER2_Data_Dictionary.csv) · [Source → ER1](docs/Source_to_ER1_Contract.csv) · [Source → ER2](docs/ER2_Source_to_Target_Mapping.csv)
- [คำอธิบายชุดข้อมูล Source](source/README.md)

## 9. ข้อจำกัดที่ควรรู้

- เป็น **Demo เพื่อการเรียน** ไม่ใช่ระบบ Production เต็มรูปแบบ ไม่มีระบบ Login/Approval ใช้ชื่อผู้ดำเนินการที่กรอกเอง
- ข้อมูลสังเคราะห์ในขนาดเล็ก (10 เดือน) ผล ML จึงมีหลักฐานจำกัด (ไม่เกินระดับ Preliminary ในชุดสาธิต) และไม่ควรนำไปสรุปเป็นผลทางธุรกิจ
- **แผนการตลาดเป็นแบบฝึกบันทึกการตัดสินใจ** ไม่ได้สั่งงานจริง และไม่เปลี่ยน Actual หรือ Forecast (Actual มาจาก Source สังเคราะห์) ผลของแผนคำนวณจากออเดอร์เดือนก่อนที่คงที่ ปรับ Ads กระทบต้นทุนและกำไร แต่ไม่ทำให้ยอดขายเพิ่ม และต้องบันทึกแผนก่อนรันเดือนนั้น
- **Forecast ทำนายก่อนมีแผน (Baseline)** ถ้าเปลี่ยนแผนจริง ส่วนต่าง Forecast vs Actual จะรวมผลของแผนด้วย จึงเป็นการวัดความแม่นแบบหยาบ แต่การเทียบ ML กับ Baseline ยังยุติธรรม เพราะทั้งสองทำนายก่อนมีแผนและใช้ Actual ตัวเดียวกัน
- Colab กับเว็บเป็นคนละระบบ ผลไม่ข้ามกัน
- ห้ามนำความลับ (รหัสผ่านฐานข้อมูล คีย์ Storage) ใส่ใน Repo หรือโน้ตบุ๊ก
