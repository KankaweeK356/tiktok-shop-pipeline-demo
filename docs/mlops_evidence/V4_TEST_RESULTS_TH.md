# Evidence v4 + Test Results จาก Full Repository ที่ Commit เดียวกัน

**Commit ที่ทดสอบและใช้สร้าง Evidence: `d766f9eeeb9e081c0a11e8771bec7780829378b5`** (working tree สะอาดตอนรัน; commit ถัดไปมีเฉพาะไฟล์เอกสาร/Evidence)
ทดสอบบนเครื่อง + Postgres ชั่วคราวเท่านั้น (ไม่เชื่อม Neon/Production)

## 1) Test Results (ทั้ง repository)
| ชุด | ผล |
|---|---|
| Postgres journey Jan→Oct (Source Final จริง, 21 เทส) | 21/21 PASS |
| Python ที่เหลือ | 155 PASS · 7 FAIL (Legacy) · 3 skipped |
| Node | 47/47 PASS |
รวม Python ทั้งหมด 176 PASS / 7 FAIL / 3 skipped. 7 FAIL คือเทสข้อความซอร์สเก่าชุดเดิมที่ล้มบน baseline `pre-mlops-8f9d67f` ด้วย (รายข้อใน UAT_REGRESSION_TH.md) ไม่เกี่ยวกับงานนี้

## 2) ข้อมูล 5 Product Groups ครบก่อน Forecast
- **พบช่องโหว่และแก้แล้ว:** ตัวสร้าง Feature ของ MLOps ตรวจครบ 5 กลุ่มทุกเดือนอยู่แล้ว แต่ `generate_forecast` (Official) เดิมเติมกลุ่มที่ขาดเป็น 0 เงียบ ๆ ตอนนี้ **หยุดและแจ้ง `FORECAST_INCOMPLETE_GROUP_MONTHS`** ถ้าเดือนใดที่ Publish ขาดกลุ่มใด (หรือมีกลุ่มแปลก)
- เทส: `test_forecast_requires_all_five_product_groups_in_every_published_month` (ตัดกลุ่มทีละแบบ 3 กรณี + กลุ่มไม่รู้จัก) และ MLOps `test_feature_table_...` (ข้อมูลไม่ครบ/ช่องว่าง)
- ข้อมูลจริง: Warehouse ที่สร้างจาก Source Final ครบ 5 กลุ่มทุกเดือน ม.ค.–ต.ค. (journey ผ่านและ Official มิถุนายนได้ ฿89,967.41 เท่าเดิม ตรวจด้วย Golden)
- ผลกระทบ: ข้อมูลที่ครบอยู่แล้วให้ผลเท่าเดิม; ข้อมูลที่ขาดจะ **ไม่ถูกพยากรณ์** แทนที่จะได้ตัวเลขผิด

## 3) Evidence v4 (สร้างใหม่จาก commit ข้างบน)
| โฟลเดอร์ | ประเภท | หมายเหตุ |
|---|---|---|
| `sample_artifacts/` | LOCAL real-source (Final source, ER2 สร้างในเครื่อง) | run.json ระบุ `code_ref: d766f9e` |
| `local_real_source_test/monitoring_journey/` | LOCAL_REAL_SOURCE_TEST | ทุก Evaluation/Summary มี `data_origin` ; Summary ล่าสุด (`through=2026-10.rev1`) นับ 5 เดือน (ก.ย. ถูกซ่อมจากหลักฐานเดิม) ; ไฟล์ `through=2026-10` เดิม (4 เดือน) เก็บเป็นประวัติ |
| `synthetic_fixtures/` | SYNTHETIC_FIXTURE | กรณี 6/7 เดือน (RECOMMEND_REVIEW / NOT_RECOMMENDED) ห้ามใช้เป็นผลจริง |
ผล Monitoring จริง (Real-source Test, 5 เดือน มิ.ย.–ต.ค., Preliminary): Cumulative WAPE Baseline 11.18% vs Ridge 13.06%; ML ชนะรายเดือน 2 จาก 5; ยังไม่ผ่านเกณฑ์/ยังไม่ถึง 6 เดือน → ไม่แนะนำเปลี่ยน Champion
