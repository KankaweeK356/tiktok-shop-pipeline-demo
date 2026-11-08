# Feature Store — คู่มือเริ่มใช้งาน (Phase 1)

## Architecture
Data Sources → Database → Data Lake → Data Warehouse → Feature Store → ML Pipeline → Decision Dashboard

งานนี้ **ไม่แก้** Database / Data Warehouse เดิม และ **ยังไม่ได้ฝึก ML หรือ Deploy Dashboard**.

## ไฟล์ที่เพิ่ม

| File | หน้าที่ |
| --- | --- |
| sql/ml_feature_store.sql | SQL สำหรับสร้าง **สองตารางใหม่** บน Supabase PostgreSQL: ml.marketing_plan และ ml.feature_daily |
| pipeline/ml_features.py | อ่าน Daily Mart จาก DuckDB และสร้าง Feature Snapshot |
| examples/ml_marketing_plan_example.csv | ตัวอย่างแผน Ads + Discount ของ Product Group PG01–PG05 (ข้อมูลสมมติ ไม่ใช่ Historical Training Plan) |
| tests/test_ml_features.py | ทดสอบการคำนวณ, Leakage, Plan Timing/Version, Missingness |
| .github/workflows/ml-feature-ci.yml | ทดสอบ Python/DuckDB บน Pull Request |

**เก็บที่ไหน?** Data Warehouse ยังคงเป็น DuckDB. Feature Builder ส่งออก Parquet/CSV ก่อน ส่วน SQL เตรียมไว้ใช้เมื่อมี Supabase. การ Commit ไฟล์ SQL **ยังไม่ได้สร้างตารางจริงใน Supabase**.

## Mapping กับ Data Warehouse (ชื่อที่ตรวจแล้วจาก schema จริง)

- Net Revenue: Mart_Product_Group_Daily_Performance.Net_Revenue
- Gross full-price sales: Mart_Product_Group_Daily_Performance.Gross_Reference_Sales
- Historical Campaign reduction: Mart_Product_Group_Daily_Performance.Campaign_Price_Reduction
- Historical Ads: Mart_Product_Group_Daily_Performance.Ads_Cost
- Date mapping: Dim_Date.Date_Key → Dim_Date.Full_Date
- Planned Ads / discount: ml.marketing_plan

Daily Mart มี Grain = Date × Product Group อยู่แล้ว. **ห้าม**นำ Ads ของ Group ไป JOIN ซ้ำกับ Sales ทีละ SKU.

## รันได้หลังจากมี Warehouse ของ Pipeline เดิม

Run existing Source → Database → Data Lake → Data Warehouse demo ให้สร้างไฟล์ output/main/er2.duckdb ก่อน

    python -m pytest -q tests/test_ml_features.py

    python -m pipeline.ml_features --db output/main/er2.duckdb \
      --plans examples/ml_marketing_plan_example.csv \
      --as-of 2026-10-31 --horizon 1 \
      --scenario DEMO_A --source-run-id initial_incremental \
      --output output/main/ml/feature_daily.parquet

ตัวอย่างนี้มีแผนเพียง 2026-11-01; หากขยาย horizon แต่ยังไม่ได้เพิ่มแผนใน CSV ต้องแสดงสถานะ **MISSING_PLAN** ไม่เติมจากค่า Ads จริงของอนาคต.

## กฎข้อมูลและการฝึก ML

1. Feature ที่เป็น Input ใช้ข้อมูลย้อนหลังถึง as_of_date เท่านั้น.
2. Planned Ads และ Campaign Discount ต้องเป็นแผนที่มี recorded_at ก่อนสิ้นสุดวัน As-of (เขตเวลา Asia/Bangkok).
3. ถ้าแผนถูกแก้ ให้เพิ่ม plan_version ใหม่; ห้ามเขียนทับประวัติเดิมจนย้อนหลังไม่ได้.
4. ผลยอดขายจริงของ Forecast Date คือ **Target/Label** สำหรับ Offline Training/Validation ไม่ใช่ Feature X.
5. เมื่อสร้าง Snapshot ย้อนหลังจาก Warehouse รุ่นล่าสุด แม้จะจำกัดวันที่ด้วย SQL ก็ยังรับรู้รายการแก้ไขย้อนหลังที่เกิดทีหลังได้ จึงถือเป็น RETROSPECTIVE_LATEST_DWH, **ไม่ใช่ Point-in-Time Verified**.
6. training_ready จึงเป็น False ตามค่าเริ่มต้น. ต้องมี archived source snapshots / revision history และแผนที่รู้ล่วงหน้าจริงจึงจะเปลี่ยนเป็น POINT_IN_TIME_VERIFIED ได้.
7. ภายในวันที่ Warehouse ครอบคลุม หากกลุ่มไม่มี Fact Row จะสมมติยอดเป็น 0 เพื่อ Demo เท่านั้น; ยังต้องมี ingestion watermark เพื่อแยกวันขาดข้อมูลออกจากวันที่ยอดเป็นศูนย์ใน Production.
8. Campaign price ใช้ **วันสร้าง Order** แต่รายได้ใน DWH ใช้ **วันชำระเงิน**. อัตราส่วนลดที่คำนวณจาก Paid-day Mart คือประวัติที่เกิดขึ้น ไม่ได้ยืนยันผลเชิงเหตุและผลของ Campaign.
9. ทุกอย่างเป็น Synthetic Data; ต้องมีข้อมูลย้อนหลังมากขึ้นและ Time-based Backtesting ก่อนสรุปคุณภาพ LightGBM.
10. Revenue Achievement คือ Net Revenue/Monthly Target; Profit Protection คือ Contribution Profit / **Gross Reference Sales** ของทั้งร้าน (เกณฑ์ขั้นต่ำ 10%) ไม่ใช่ Profit/Net Revenue.

## ยังไม่รวมใน Phase 1 นี้

- ขยาย Mock Source เป็นข้อมูลย้อนหลังที่เพียงพอพร้อม Archived Point-in-Time State
- สร้าง Feature Training Dataset หลายวันและทดสอบ Backtesting
- ฝึก Seasonal Naive / LightGBM และประเมิน MAE, WAPE, Bias
- Run Model Serving, Monitoring, Supabase integration และ Decision Dashboard

**ไม่ควรอ้างว่าโมเดลรู้ว่าการเพิ่ม Ads จะทำให้ยอดขายเพิ่มเท่าไรอย่างเป็นเหตุเป็นผล** จนกว่าจะมีการประเมินที่รองรับเรื่องนั้น.
