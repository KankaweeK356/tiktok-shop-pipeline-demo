# UAT Results — MLOps (ขั้น 3–6) · branch `claude/mlops-feature-store`

| รายการ | ผล |
|---|---|
| Journey Jan→Oct บน Postgres + worker จริง (17 เทส รวมเทส 17: รัน Historical/Experiment แล้ว forecast ที่ Seal, Actual, แผน เหมือนเดิมทุกไบต์) | 17/17 ผ่าน |
| Feature Store / Report / Drift / UI-API contract (`tests/test_mlops_feature_store.py`) | 19/19 ผ่าน |
| Node (รวม API `fc=mlops` อ่านจาก Artifact จริง) | 38/38 ผ่าน |
| Python ทั้งหมด (ไม่รวมไฟล์ Postgres) | 124 ผ่าน, 7 ล้ม (Legacy ด้านล่าง), 3 skipped |
| Golden June (Shop + Product Group) | Baseline ตรรกะเดิมได้ ฿89,967.41 = Official ที่ Seal; ทดสอบใน test_mlops_feature_store (golden) และ Node (`official_selection.shop_prediction`) |
| Point-in-time / Leakage / Write-once / Artifact ครบ | ผ่านใน test_mlops_feature_store |
| MLOps ล้มแล้ว Official Forecast/Business Dashboard ไม่เสีย | ผ่าน: worker ครอบ try/except (เคยล้มจริง 1 ครั้งใน dev, forecast ยังสร้างได้) และ API คืน 503 ธรรมดาโดย `fc=status` ยังทำงาน (Node test) |

## 7 Legacy Failing Tests (ล้มเหมือนกันบน baseline `pre-mlops-8f9d67f` ก่อนเริ่มงานนี้)
เทสทั้ง 7 ตรวจ "ข้อความซอร์สเก่า" ที่ไม่มีในโค้ดที่ Deploy อยู่แล้วก่อนงาน MLOps (รันบน worktree ของ tag `pre-mlops-8f9d67f` ได้ 7 ข้อเดียวกันนี้ล้ม):

| เทส | สาเหตุ |
|---|---|
| test_pipeline_lab::test_lab_uses_live_neon_and_actual_parquet_not_fake_rows | หา `state.labResults[def.id]=payload` ใน app.js ซึ่งถูกรื้อไปก่อนหน้า |
| test_pipeline_lab::test_group_and_sku_are_distinct_profit_grains | หา `metric("คุ้มครองกำไร",pct(current.protection_pct)` / `current.protection_status` ที่ถูกแทนด้วย Business v3+ |
| test_real_lab::test_real_one_step_python_contract | หา `complete_run(db_url` ใน pipeline เดิมที่ refactor แล้ว |
| test_real_lab::test_frontend_labels_real_execution_distinct_from_readonly_replay | ข้อความ label เก่าใน app.js |
| test_real_lab::test_complete_run_dispatch_keeps_token_server_side_and_checks_phase | หา `CLASSROOM_GITHUB_TOKEN` ใน api/lab-batch.js (เปลี่ยนเป็น Vercel worker ไปแล้ว) |
| test_real_lab::test_reset_button_does_not_request_browser_password | หา `["RUN1_READY","RUN2_READY"].includes(state?.phase)` ใน api/lab-reset.js |
| test_real_lab::test_actual_lab_isolated_from_protected_900_order_demo | หา `CLASSROOM_LAB_NEON_URL` ใน api/lab-batch.js |

งานนี้ไม่ได้แก้ api/lab-batch.js, api/lab-reset.js, pipeline เดิม; ที่แก้ใน app.js คือเพิ่มส่วน ML Panel ท้ายหน้า Forecast เท่านั้น
(บน baseline มีเทสที่ 8 `test_node_unit_tests_for_pipeline_state_and_review_fix_api` ล้มด้วย เพราะ worktree ไม่มี node_modules ที่ต้องใช้ ไม่เกี่ยวกับโค้ด; บน branch นี้ผ่าน)
