# Phase 2 — Historical Mock Data for ML\n\n> **ขอบเขต:** ไฟล์นี้อธิบายชุด legacy October/November ที่ใช้เป็นฐานข้อมูลประวัติของ ML และใช้สร้าง Source รายเดือน. 800 Orders อยู่ใน October fixture และ 100 Orders อยู่ใน November fixture; ตัวเลขนี้ไม่ใช่จำนวนของ Run 1/Run 2 ปัจจุบันใน Colab ซึ่งเริ่ม January และเพิ่มทีละเดือนถึง October.

## วัตถุประสงค์
เพิ่มข้อมูลสังเคราะห์ย้อนหลังสำหรับ Marketing-Aware Sales Forecasting โดยไม่เปลี่ยน Database 25 ตารางหรือ Data Warehouse 6 Dimensions / 4 Facts / Daily Mart และไม่เขียนทับ Source Demo เดิม

**Architecture:** Data Sources → Database → Data Lake → Data Warehouse → Feature Store → ML Pipeline → Decision Dashboard

## ช่วงข้อมูล
- Demo เดิมใน source/: October 2026 initial 800 Orders + November 2026 incremental 100 Orders, กรณี Update/Replay เดิม
- Historical Mock ใหม่ใน output/ml_history_ci/source/: November 2025–September 2026 + October 2026 เดิม = ประวัติครบ 12 เดือน
- Incremental ในโปรไฟล์ ML: November 2026 ตามการทดสอบเดิม
- แผนการตลาดอยู่แยกที่ output/ml_history_ci/source/ml_marketing_plan.csv (ไม่เพิ่มตาราง Database)

## สิ่งที่ Mock
1. Fact_Orders, Fact_Order_Items, Fact_Internal_Fulfillment — รายการขายรายวัน มี Group, SKU, ราคา, Affiliate และต้นทุนผ่าน Pipeline เดิม
2. Fact_Marketing_Costs — Ads ระดับ Date × Product Group ตลอดช่วงย้อนหลัง ไม่ใช่ Ads × SKU
3. Dim_Campaign + Bridge_Campaign_Product_Group — Campaign 2 Wave ต่อเดือน ราคาและส่วนลดแตกต่างกันตาม Group พร้อมตรวจว่าไม่ซ้อนช่วง
4. แผนการตลาดประจำวัน — Budget, Discount, Scenario, Version และเวลาที่บันทึกไว้ก่อนวันที่ใช้แผน
5. Fact_Goods_Receipt สำหรับ Lot ในช่วงย้อนหลัง, Monthly Business Targets, วันที่และรอบงวดใน Dim_Date

Seed 8102, จำนวน Product Group 5 และ SKU 140 เท่าเดิม. Actual Ads จำลองให้ต่างจาก Planned Budget; Demand มีช่วงสัปดาห์ ฤดูกาล และความสุ่ม เพื่อไม่ให้ข้อมูลถูกกำหนดด้วยสูตรง่ายเกินไป

**ทุกข้อมูลเป็น Synthetic เพื่อการศึกษา ไม่ใช่ข้อมูล TikTok จริงหรือหลักฐานการเพิ่มยอดขายเชิงเหตุและผลจาก Ads**

## วิธีรัน
หลังติดตั้ง requirements.txt ตามเดิม:

    python -m pipeline.generate_ml_history --output output/ml_history_ci/source
    python -m pipeline.ci_ml_history

คำสั่งที่สองจะสร้าง Source อีกครั้งด้วย Seed เดิม แล้วรัน Initial → Incremental → Replay พร้อมตรวจ Data Quality, Reconciliation และ Feature Preview

ไฟล์ผลสำคัญ:
- output/ml_history_ci/source/initial/*.csv
- output/ml_history_ci/source/incremental/*.csv
- output/ml_history_ci/source/ml_marketing_plan.csv
- output/ml_history_ci/main/er1.sqlite
- output/ml_history_ci/main/lake/
- output/ml_history_ci/main/er2.duckdb
- output/ml_history_ci/main/reports/ml_history_summary.json
- output/ml_history_ci/main/reports/ml_history_monthly_kpi.csv
- output/ml_history_ci/main/reports/ml_history_group_monthly.csv
- output/ml_history_ci/main/reports/ml_history_feature_preview.csv

## GitHub Actions
Workflow ML Historical Mock - Full Data Pipeline จะทดสอบ Generator และ End-to-End ETL พร้อมเผยแพร่ Artifact ชื่อ tiktok-12-month-synthetic-ml-history (เก็บ 14 วัน) ซึ่งประกอบด้วย Source CSV, แผนการตลาด และรายงานจากการรันจริง

## จุดระวังสำหรับ ML
- Historical Plans สร้างด้วยสูตรจำลองและสมมติว่าทราบล่วงหน้า ไม่ใช่ History จากระบบการตลาดจริง
- Feature Builder ที่อ่านจาก Current Data Warehouse ยังคงถูกระบุ RETROSPECTIVE_LATEST_DWH และ training_ready=False จนกว่าจะมีหลักฐาน Point-in-Time Snapshot
- Campaign กำหนดราคาตาม Order Created แต่รายได้ใช้ Paid Date; การสรุปผลต้องไม่สับสนสองวัน
- การเพิ่ม Ads และส่วนลดภายในตัวสร้างข้อมูลจำลองไม่ได้ยืนยันผลเชิงเหตุและผลในร้านจริง
- ยอดขายและกำไรทุกตัวต้องตรวจใน Data Warehouse; ไม่หักค่า Discounts/Ads ซ้ำ
- 12 เดือนเป็นข้อมูลฝึก Demo ที่ต้องผ่าน Backtesting ก่อนอ้างประสิทธิภาพโมเดล
- Phase 2 ยังไม่รวมการฝึก LightGBM, Supabase และ Decision Dashboard
