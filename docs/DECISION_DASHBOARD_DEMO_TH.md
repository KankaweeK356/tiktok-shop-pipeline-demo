# Phase 4 — Decision Dashboard (Classroom Demo)

## ภาพรวม
เว็บ Static แบบไม่ต้องเปิด ML Server ค้างไว้ มี 3 หน้า: Business Overview, Pipeline Explorer และ ML Lab & Monitoring

**ทุกตัวเลขต้องสร้างจาก Pipeline และ ML Report จริงในโปรเจกต์** ไม่ hardcode คะแนน WAPE หรือยอดขาย และข้อมูลทั้งหมดเป็น SYNTHETIC สำหรับการศึกษา

## เส้นทางข้อมูล
Source CSV → SQLite Database → Parquet Data Lake → DuckDB Data Warehouse → Offline Feature Dataset → LightGBM/Naive → Saved Evaluation, Serving Replay, Monitoring → Static JSON → Dashboard

ส่วน Static JSON คือ dashboard/data/report.json สร้างใหม่ได้ด้วย pipeline/export_dashboard.py เมื่อ rerun ETL/ML และ Commit snapshot เพื่อให้เว็บ Vercel แสดงผลได้โดยไม่ต้องมี Python Server ทำงานตลอด

## หน้าจอและความหมาย

1. **Business Overview:** เลือกเดือน/กลุ่ม ดู Net Revenue, Gross Reference Sales, Ads Cost, Campaign Reduction, Contribution Profit, Monthly Target/Revenue Achievement และ Profit Protection (Contribution Profit / Gross Reference Sales) เฉพาะระดับทั้งร้านเท่านั้น; Group เป็นการวิเคราะห์ ไม่กระจายเป้าหมายร้านไปตัดสินรายกลุ่ม
2. **Pipeline Explorer:** เห็นแหล่ง Data, Stages Initial+Incremental ที่ผ่านและเวลาประมวลผล, ER1/ER2, Reconciliation, Ads Fact-to-Mart และตัวอย่าง Item Lineage ถ้ามี; การ Recovery ใน Historical Run ระบุ NOT_RUN ตรง ๆ
3. **ML Lab:** เปรียบเทียบ 3 โมเดลจาก Rolling Validation/Final Test ราย Group/Shop, Feature Importance, Data Preview, Archived Prediction, Saved Model Serving Replay และ Monitoring Alerts

**Marketing Plan Sandbox:** ปรับงบ/ส่วนลดเพื่อดูเปรียบเทียบกับแผนอ้างอิง ไม่ทำนาย Revenue/Profit/ROI ภายใต้การปรับตัวเลข เพราะโมเดลที่มีเป็น Forecast เชิงความสัมพันธ์ ไม่ใช่ Causal Uplift Engine

## รัน/ตรวจในเครื่อง (หลังติดตั้ง Python requirements-ml.txt)

    python -m pipeline.ci_ml_history
    python -m pipeline.ci_ml_weekly_demo
    python -m pipeline.export_dashboard
    python -m pytest -q tests/test_dashboard.py
    python -m http.server 8000 --directory dashboard

เปิด http://localhost:8000 ใน Browser ห้ามเปิด HTML ด้วย file:// เพราะ fetch JSON จะถูกบล็อก

## การนำขึ้น Vercel
1. Connect GitHub repo KankaweeK356/tiktok-shop-pipeline-demo ไปยัง Vercel
2. เลือก Branch main; Root Directory = Repository Root
3. ใช้ vercel.json ที่กำหนด outputDirectory=dashboard
4. Deploy เว็บไซต์ Static (ไม่ต้องตั้ง Token/TikTok API/Database Secrets)
5. **ต้องมี dashboard/data/report.json ที่สร้างจริงอยู่ใน main**; ถ้าไม่มีหน้าเว็บจะขึ้นข้อความ Data unavailable

Vercel ไม่ได้รัน Python Training โดยอัตโนมัติ เมื่อมีการสร้าง Mock/ฝึกโมเดลใหม่ ให้ Generate dashboard/data/report.json ใหม่จาก Warehouse แล้ว Commit ก่อน Deploy ใหม่

## คุณภาพและข้อจำกัด
- Data Classification: SYNTHETIC_EDUCATIONAL_NOT_TIKTOK
- Model Approval: DEMO_ONLY_NOT_PRODUCTION
- Date/Time เป็น Batch Snapshot ไม่ใช่ Data Pipeline สด
- Revenue Target Achievement = Net Revenue / Monthly Target
- Profit Protection Rate = Contribution Profit / Gross Reference Sales, มีเงื่อนไขต้นทุนครบ
- Group WAPE และ Shop WAPE ใช้ Grain ต่างกัน ต้องแยกการอ่านผล
- Archived Predictions ใช้ชุด Test ที่โมเดลทำนายจริง; Serving Replay ทำเฉพาะสัปดาห์/โมเดลที่ถูกโหลดใหม่ใน CI
- หน้ากรอก Ads/Discount **ไม่เปลี่ยน Prediction** และไม่ได้อ้าง causal ROI
- Snapshot ล่าสุดรวม Initial Oct 2026 และ Incremental Nov 2026 โดย Nov เป็นเพียงการอัปเดตช่วงต้นเดือน ไม่ใช่เดือนที่ปิดยอดแล้ว

## Demo ต่อหน้าอาจารย์ที่แนะนำ
1. เปิด Pipeline Explorer → ชี้ Source → Database → Lake → Warehouse, Reconciliation และ Lineage
2. เปิด Business Overview → เปรียบเทียบยอดขาย/เป้าหมาย/กำไร และกฎ Profit Protection
3. เปิด ML Lab → เปลี่ยนโมเดลดู Validation/Test จริงและ WAPE Group/Shop
4. กดเลือกสัปดาห์สุดท้าย → ดูผล Serving Replay + Monitoring Alerts
5. ลองเปลี่ยน Ads/Discount → อธิบายแผนจำลองและข้อจำกัดของการพยากรณ์
6. เปิด Source GitHub และ Report JSON เมื่อถูกถามถึง Data Lineage หรือสูตร

## งานที่ยังเหลือ
- การ Deploy เว็บไปยัง Vercel account ต้องเปิด Project/เชื่อม GitHub ก่อน (จากโค้ดอย่างเดียวไม่ได้สร้าง URL ที่ออนไลน์)
- Online Serving, Auth, Persistent Scenario Storage, ML Observability และ Causal/What-if forecasting ยังไม่อยู่ใน Scope Demo นี้
