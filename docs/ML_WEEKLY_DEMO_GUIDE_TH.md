# คู่มือ Demo MLOps — TikTok Shop (Synthetic Data)

**สิ่งที่ Demo:** Source จำลอง → Database → Data Lake → Data Warehouse → Weekly ML → Model Serving Replay → Monitoring

**ข้อจำกัด:** ไม่ใช่ Production System และไม่ใช่เครื่องมือที่พิสูจน์ผลเชิงเหตุและผลจาก Ads หรือส่วนลดแล้ว

## วิธีเปิด Demo

1. เข้า GitHub Repository → Actions → Workflow: Weekly MLOps Demo - Synthetic Real Training Serving Monitoring
2. เมื่อรวม Workflow เข้า main แล้ว กด Run workflow หรือเปิด Run ที่ผ่านใน Pull Request
3. ดูสถานะ Test, Source/Database/Lake/DWH, Model Training, Serving & Monitoring — ต้องเป็น SUCCESS
4. ในหน้า Run เปิด Artifacts → weekly-mlops-demo-real-reports และดาวน์โหลด ZIP
5. เปิดไฟล์ผลลัพธ์ที่บันทึกจากการรันจริงเพื่ออธิบายกับอาจารย์

## 8 ขั้นที่แสดงกับอาจารย์

| ขั้น | อธิบาย | ไฟล์หลักฐาน |
|---|---|---|
| 1. Data Extraction | อ่าน Mock CSV → SQLite → Parquet → DuckDB | Pipeline CI / Functional Validation |
| 2. EDA | วิเคราะห์ยอดขายและกำไรรายเดือน/ราย Product Group | ml_history_monthly_kpi.csv, ml_history_group_monthly.csv |
| 3. Data Preparation | สร้าง Features แบบรู้ข้อมูล ณ วัน Forecast; Label ใช้ยอดสัปดาห์ถัดไป | weekly_training_dataset.parquet |
| 4. Model Training | ฝึก Baseline, Historical LightGBM, Marketing LightGBM | weekly_history_model.txt, weekly_marketing_model.txt |
| 5. Model Evaluation | วัด MAE, WAPE, Bias บน Test | weekly_test_metrics.csv, weekly_test_by_group.csv |
| 6. Model Validation | Rolling Validation 3 รอบก่อนดูผล Test | weekly_rolling_folds.csv, weekly_model_selection.csv |
| 7. Model Serving | โหลด Model Artifact ที่บันทึกไว้แล้วทำนายใหม่ | serving_replay_predictions.csv, weekly_model_registry.json |
| 8. Model Monitoring | ตรวจ Prediction เทียบกับ Actual ที่ทราบภายหลัง แล้วสร้าง Alert | serving_monitor_replay.json |

**Serving และ Monitoring เป็น Offline Replay เท่านั้น** แต่ ML ทำนายจาก Model Artifact จริง ไม่ใช่แสดงตัวเลขที่กำหนดล่วงหน้า

## ทำไมเปลี่ยนเป็นรายสัปดาห์

- ข้อมูล Mock รายวันมี Order ไม่มากและค่อนข้างผันผวน
- การทำนายสัปดาห์จันทร์–อาทิตย์ช่วยสาธิตการวางแผนการตลาดได้ชัดขึ้น
- ต้องรายงาน WAPE ทั้ง Product Group และทั้ง Shop (ข้อผิดพลาดรายกลุ่มอาจหักล้างกันเมื่อรวมร้าน)
- เกณฑ์เป้าหมายสำหรับ Demo: Group WAPE <= 20% และ Shop WAPE <= 15%; เป็น Target ไม่ใช่การรับประกันว่า Model ผ่าน

## โมเดลที่เปรียบเทียบ

1. Last Week Naive: ใช้ยอดสัปดาห์ก่อน
2. LightGBM History: ยอดย้อนหลัง ค่า Ads และส่วนลดที่เกิดขึ้นแล้ว Calendar
3. LightGBM Marketing: เหมือนข้อ 2 และเพิ่ม Planned Ads/Campaign สำหรับสัปดาห์เป้าหมาย

โมเดลข้อ 3 ไม่ได้พิสูจน์ว่าการเพิ่ม Ads เป็นสาเหตุให้ยอดขายเพิ่มขึ้นจริง

## ถ้าต้องการให้ข้อมูล Mock ผันผวนน้อยลง

Generator เดิมรองรับการเพิ่มค่าเฉลี่ย Orders ต่อ Product Group ต่อวันแล้ว ควรสร้างเป็น Profile แยกเพื่อไม่กระทบ Demo เก่า เช่น:

    python -m pipeline.generate_ml_history --output output/ml_history_alt/source --base-orders-per-group-day 5

หลังสร้าง Source โปรไฟล์ใหม่ ต้องรัน Database → Data Lake → DWH → ML Training ใหม่ครบ ไม่ใช่แค่เปลี่ยนตัวเลข WAPE บนรายงาน และต้องแสดงทุก Profile ที่ทดลอง ไม่คัดเฉพาะกรณีที่ได้คะแนนดี

## ขอบเขตที่ต้องบอกอาจารย์

- ข้อมูลทั้งหมด Synthetic; ไม่เชื่อม API TikTok
- Current DWH Snapshot ยังไม่ยืนยัน Historical Point-in-Time เมื่อมี Late Corrections
- Recorded-at ของ Marketing Plan เป็นข้อมูลสังเคราะห์ที่สมมติว่าทราบล่วงหน้า
- Model ยังเป็น DEMO_ONLY_NOT_PRODUCTION
- ยังไม่ได้เปิดบริการ API หรือ Deploy Decision Dashboard บน Vercel
- KPI ธุรกิจที่ต้องคงไว้: Revenue Target Achievement >=100% และ Profit Protection >=10% ของ Gross Reference Sales (ไม่ใช่ 10% ของ Net Revenue)

## ขั้นตอนถัดไป

ทำ Decision Dashboard ที่แสดงผลจริงจาก Pipeline/Model/Serving/Monitoring ผ่าน 3 มุมมอง: Pipeline Explorer, ML Lab และ Business Decision View โดยไม่แต่งตัวเลขผลทำนายเอง
