# Phase 3 — ML Training Dataset & Time-based Backtesting

## Business question

ร้านควรใช้กิจกรรมการตลาด (Ads Spend / Campaign Discount) อย่างไรเพื่อเพิ่มโอกาสทำ Revenue Target โดยยังรักษา Profit Protection >=10% ของ **Gross Reference Sales**?

**Phase 3 ตอบได้เฉพาะว่าการพยากรณ์ภายใต้ตัวแปรการตลาดแม่นกว่า Baseline หรือไม่** ยังไม่ทำนายผลเชิงเหตุและผลของการเพิ่ม Ads/ลดราคา และยังไม่รับรองการแนะนำแผนที่ดีที่สุด

## Data Architecture

Data Sources → Database → Data Lake → Data Warehouse → Feature Store → ML Pipeline → Decision Dashboard

- ใช้ Data Warehouse DuckDB เดิม, 5 Product Groups, 140 SKUs
- ประวัติ Synthetic Nov 2025–Oct 2026 ผ่าน Source → Database → Data Lake → Data Warehouse
- ใช้ Marketing Plans จำลองที่กำหนด 35 วันล่วงหน้า
- ข้อมูล Order/Campaign/Ads ทั้งหมดจำลอง ไม่ใช่ข้อมูลจริงจาก TikTok
- ไม่มีการแก้ ER Diagram หรือเพิ่มตารางลง Database/DWH เดิม

## Feature Dataset

หนึ่งแถว = As-of Date × Forecast Date × Product Group × Scenario; Horizon 1–7 วัน

Feature:
- lag 1 วันและ lag 7 วัน ณ วัน As-of
- rolling revenue 7/28 วัน
- actual Ads ย้อนหลัง 7 วัน
- campaign discount ratio ย้อนหลัง 7 วัน
- planned Ads ของวันที่จะพยากรณ์
- planned Campaign discount ของวันที่จะพยากรณ์
- group, month, weekday, forecast horizon

Target/Label คือ Net Revenue ของวัน Forecast Date โดย **ห้ามใช้เป็น Input X**.

Seasonal Naive ทำนายยอดขายของวันเดียวกันในสัปดาห์ก่อน: Forecast Date - 7 วัน (ไม่ใช่ As-of - 7 วัน). เมื่อ Horizon ไม่เกิน 7 วัน ค่านี้จึงรู้ได้ก่อนเวลาทำนาย

## Train, Validation and Locked Test

**ห้ามสุ่มข้อมูลรายแถว** เพราะ Forecast Date เดียวกันมีหลาย As-of/horizon และจะเกิด Data Leakage

Rolling-fold validation:
- F1 Train target ถึง 30 Apr 2026 → Validate May 2026
- F2 Train target ถึง 31 May 2026 → Validate Jun 2026
- F3 Train target ถึง 30 Jun 2026 → Validate Jul 2026

Locked Final Test:
- Refit selected architectures using labels ถึง 31 Jul 2026
- Evaluate **1 Aug – 30 Sep 2026**
- Oct 2026 ถูกกันไว้ ไม่ใช้เลือกโมเดล

Model comparison:
1. Seasonal Naive
2. LightGBM with historical sales/time/group features only
3. LightGBM with historical sales + historical marketing + planned Ads/Campaign

Model selection ใช้ WAPE เฉลี่ยแบบถ่วงน้ำหนัก Actual Turnover ของ Validation Fold เท่านั้น ไม่ใช้ผล Test เลือกโมเดล

Test รายงานทั้ง 3 วิธีเพื่อความโปร่งใส ไม่สมมติว่า Marketing-Aware ต้องชนะ และไม่เปลี่ยนกลยุทธ์จนกว่าจะทดสอบจริง

## เกณฑ์ Metrics

- MAE (บาท): mean absolute forecast error
- WAPE (%): SUM(abs(actual-predicted))/SUM(abs(actual))*100
- Bias (%): SUM(predicted-actual)/SUM(abs(actual))*100; บวก = ทำนายสูงไป
- ดูแยก Product Group และ Forecast Horizon
- Metric นี้วัด Forecast Accuracy ไม่ใช่ Causal Marketing Uplift

## Run

    pip install -r requirements-ml.txt
    python -m pytest -q tests/test_ml_backtest.py tests/test_ml_history.py tests/test_ml_features.py
    python -m pipeline.ci_ml_history
    python -m pipeline.ci_ml_backtest

Artifacts หลังรัน:
- offline_feature_dataset.parquet — feature snapshots + target / status
- fold_validation_metrics.csv — 3 folds × 3 models
- model_selection_metrics.csv — เลือกจาก Validation เท่านั้น
- test_overall_metrics.csv — actual vs forecast metrics ทั้ง 3 วิธี
- test_group_metrics.csv — ทดสอบแยก 5 Product Groups
- test_horizon_metrics.csv — ทดสอบ Horizon 1–7 วัน
- test_predictions.csv — วัน As-of, Forecast Date, Group, Target, Prediction, Model
- model_history.txt / model_marketing.txt — LightGBM artifacts ที่ฝึกจริง
- marketing_feature_importance.csv — Gain importance (ความสัมพันธ์เชิงพยากรณ์ ไม่ใช่ causal effect)
- backtest_summary.json — Model Version, Data Fidelity, Holdout Window, Selection Reason, Warnings

GitHub Actions จะรันอัตโนมัติบน PR และเก็บไฟล์ผลภายใน Artifact ของ Workflow

## ข้อจำกัดที่ต้องชี้แจงกับอาจารย์และหน้าจอ Decision Dashboard

**RESEARCH_ONLY_NOT_PRODUCTION_APPROVED**

แม้ตัวสร้าง Marketing Plans จะทำให้ recorded_at อยู่ก่อนวันใช้แผน 35 วัน แต่ Training Feature จาก DuckDB Snapshot ล่าสุดยังไม่เท่ากับ Historical Point-in-Time Snapshot ที่ตรวจย้อนหลังได้ครบถ้วน เพราะอาจมี Late-arriving Corrections

Phase 3 จึงทดลอง ML เพื่อใช้เป็นหลักฐานด้านการเรียนและสาธิต MLOps เท่านั้น โดยตั้ง history_fidelity=RETROSPECTIVE_LATEST_DWH และ training_ready=False อย่างต่อเนื่อง

การเปรียบเทียบตัวเลข Forecast ภายใต้ Ads หรือ Discount ต่างกันไม่ได้แปลว่า Ads/Discount เป็นสาเหตุของการเพิ่มยอดขาย และกรณี Scenario ที่อยู่นอกช่วงข้อมูลฝึกต้องแสดงข้อจำกัดความน่าเชื่อถือ

Phase 4 ต่อไปจึงจะออกแบบ Prediction/Model Registry/Monitoring และ Profit Projection Engine ที่เชื่อมเป็น Decision Dashboard โดยตรวจ Gross Reference Sales, Cost Completeness, Profit Protection ตามกฎ DWH เดิมและห้ามนับต้นทุนซ้ำ
