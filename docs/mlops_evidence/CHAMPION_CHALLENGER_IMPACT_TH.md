# Impact Assessment — Champion–Challenger Monitoring (revision 2: scope ลดลงตามนโยบาย Academic Demo)

Branch `claude/champion-challenger-monitoring` · ยังไม่ merge · ไม่ deploy Production · ไม่ migration · ไม่แก้ข้อมูล Production

## 1) Scope ที่ปรับ
ตัดตามคำสั่ง: ไม่มี Approver ID / Login / Approval API / Approval Ledger / ฟังก์ชันเปลี่ยน Champion ผ่านหน้าเว็บ (มีเทสตรวจว่าไม่มีคำเหล่านี้ใน API)
คงมาตรการเดิม: ticket ที่เซ็นด้วย admin key, ตรวจ same-origin, ไม่รับ SQL/secret จากเบราว์เซอร์, ไม่มี secret ในโค้ด

## 2) นโยบายที่ทำงานอยู่จริง
| ข้อ | การทำงาน | หลักฐานทดสอบ |
|---|---|---|
| 1 Baseline = Official Champion (ดีที่สุดระหว่าง trailing 3 กับ naive) | `generate_forecast(..., allow_ml=False)` ยังคำนวณ walk-forward ครบ แต่ **ไม่เลือก ML** ถึงแม้ ML ชนะ (บันทึกเหตุผล + `ml_passed_validation_blocked_by_policy`) การเลือก Baseline ที่ดีที่สุดเป็นตรรกะเดิม | `test_ml_is_never_selected_as_official_even_when_it_wins_walk_forward` (Fixture ที่ตรรกะเดิมเลือก ML จริง → ได้ BASELINE) |
| 5 ห้ามเปลี่ยนเป็น ML อัตโนมัติ — ทุกเส้นทาง | (ก) ทุกจุดเรียก `generate_forecast` ในโค้ดส่ง `allow_ml=False` (ข) worker มี guard `LAB_POLICY_ML_NOT_OFFICIAL` ก่อนบันทึกอะไร (ค) Seal/Node ไม่เปลี่ยน method (ง) ไม่มีแถว `method_type='ML'` ในฐานข้อมูลเลย | `test_every_official_forecast_call_site...` (สแกนโค้ด), Postgres `test_12b` (spy ว่า worker ส่ง allow_ml=False; ฉีดผล ML → ถูกบล็อกและไม่เขียนแถวใด), `test_18` (`SELECT DISTINCT method_type` = BASELINE เท่านั้น) |
| 2 Ridge = Challenger + Shadow | `shadow_forecast.json` (Target Month, Created At, Data Cutoff, Feature Version, Model Version ของ Baseline ทั้งสองแบบและ Ridge, ราย 5 กลุ่ม + ยอดร้าน) เขียนครั้งเดียว | test_training_run_writes_a_shadow... |
| 3 สถานะ Insufficient / Preliminary / Adequate / RECOMMEND_REVIEW | เกณฑ์เดิมไม่เปลี่ยน (3/6 เดือน, ≥2 จุด, 4 จาก 6, กลุ่ม ≤5 จุด) | ทดสอบขอบเขตทุกเกณฑ์ |
| 4 RECOMMEND_REVIEW = คำแนะนำพร้อมหลักฐาน | `recommendation.evidence` (เดือนที่นับ, Forecast ID, Shadow Run) + ข้อความ "ระบบนี้ไม่มีฟังก์ชันเปลี่ยน Champion" `champion_change_function_in_system=false` | test_recommendation_carries_its_evidence... |
| 6 ไม่แก้ Forecast ที่ Seal | Monitoring อ่านอย่างเดียว | Postgres `test_18`: มิถุนายนเดิม (ผลราย 5 กลุ่ม, sealed_at, Forecast ID) ตรงกับตอน Seal; Golden ฿89,967.41 ในเทสข้อมูลจริง |
| 7 เทียบกับ Baseline ที่ใช้เป็น Official จริงแต่ละเดือน | Champion ฝั่ง Monitoring = ค่าที่ **Seal จริงใน DB** ของเดือนนั้น (trailing 3 หรือ naive) ตรวจเทียบกับ Baseline ใน Shadow ถ้าไม่ตรง → ไม่นับ (`OFFICIAL_BASELINE_MISMATCH`) ถ้า Official ไม่ใช่ Baseline → ไม่นับ | test_champion_is_the_official_baseline_actually_sealed_each_month, test_18 (Oracle อิสระ) |
| 8 Model/Feature Version + ประวัติ | อยู่ใน Shadow, Training Run, evaluation รายเดือน (ทุกไฟล์ write-once) | — |

ผลข้างเคียงที่ต้องรู้: `official_logic_result` ใน Training Run ตอนนี้บันทึกผลของนโยบาย (`allow_ml=False`) และเพิ่ม `ml_would_be_selected_without_policy` เพื่อให้เห็นว่าตรรกะเดิมเพียงลำพังจะเลือก ML หรือไม่

## 3) การแก้ที่ขอก่อนปิดงาน
| รายการ | ผล |
|---|---|
| ไม่ Hardcode ปี/ช่วง Lab, ข้ามปีได้ | `monitoring.py` ใช้ `month_add` และหน้าต่าง 36 เดือนย้อนหลังจากเดือนที่ประเมิน (ไม่มี list เดือนตายตัว); Node probe `through=` ย้อนจากเดือนล่าสุดที่ Publish; ทดสอบ พ.ย. 2026 → เม.ย. 2027 และ stream ข้ามปี/ข้าม cycle. **ขอบเขต:** ตัว Pipeline/Forecast gate ของ Lab (10 batch, 2026) ไม่ได้แก้ |
| สะสมข้าม Dataset Cycle | เก็บเป็น **stream** (`lab-cycle-{n}` ค่าเริ่มต้น หรือ `CLASSROOM_MONITORING_STREAM` สำหรับ stream ยาว): คนละ Cycle ไม่ปนกัน, เดือนเดียวกันใน stream เดียวนับครั้งเดียว (`ALREADY_RECORDED`), stream ยาวรวมหลาย Cycle ได้ (เก็บ `cycle` ในแต่ละแถว) เทสทั้งสามกรณี |
| แยกข้อมูลจำลองจาก Production | ทุก summary มี `data_origin` (`SYNTHETIC_FIXTURE` / `LOCAL_REAL_SOURCE_TEST` / `LAB_RUNTIME` / `PRODUCTION`), UI แสดงแถบเตือนเมื่อเป็นสองแบบแรก, โฟลเดอร์ `evidence/synthetic_fixtures/` แยกจาก `evidence/local_real_source_test/`, ชื่อ Screenshot ขึ้นต้นด้วยประเภท **ยังไม่มี PRODUCTION evidence** (ยังไม่ deploy) |
| ML ไม่เป็น Official โดยไม่มี Human Approval | ตามขอบเขตใหม่ ระบบไม่มีเส้นทางใดเปลี่ยนเป็น ML เลย (ดูข้อ 5 ด้านบน) การเปลี่ยน Champion ทำนอกระบบ Demo |
| Official มิถุนายนเดิมไม่เปลี่ยน | ผ่าน (ดูข้อ 6) |
| Deployment Readiness | ดูข้อ 4 |

## 4) Deployment Readiness (ยังไม่ได้ deploy — เป็นเช็กลิสต์)
- **สิทธิ์ Storage:** worker ต้องเขียนได้ใน `vercel-lab/ml/**`; ฝั่ง API ต้องอ่านได้ Monitoring ใช้ key ตายตัว (ไม่ต้อง List) แต่หน้า Training Run เดิม (`fc=mlops`) ใช้ ListObjectsV2 ยังต้องตรวจกับ Neon bucket จริง
- **สิทธิ์ DB:** ใช้ role เดิม อ่าน `demo_ml.forecast_run/forecast_result` และ `demo_control.pipeline_runs` เท่านั้น ไม่มีการเขียนตารางเพิ่ม ไม่มี migration
- **Concurrent writes:** Object Storage เป็น check-then-write (ไม่มี conditional write ที่ยืนยันแล้ว) จึงครอบการประเมิน/สรุปด้วย **Postgres advisory lock ต่อ stream** (`pipeline/mlops/locks.py`) Postgres `test_19` พิสูจน์ว่า 4 threads พร้อมกัน → มีผู้ชนะ 1 คน ที่เหลือ `ALREADY_RECORDED` และ **ถ้าไม่ใช้ lock เกิด race จริง** (เหตุผลที่ต้องมี)
- **ข้อจำกัดที่เหลือ:** write-once เป็นระดับแอป ไม่ใช่ Object Lock; ลำดับเวลา "บันทึกก่อน Publish" ใช้เวลา Worker เทียบเวลา Neon; `INVOCATION_LOCK` เดิมยังเป็นระดับ process
- **Secret:** ไม่มี secret ใหม่; `CLASSROOM_EVIDENCE_ORIGIN` / `CLASSROOM_MONITORING_STREAM` เป็นค่าตั้งแบบไม่ลับ (ไม่ตั้ง = `LAB_RUNTIME` / `lab-cycle-{cycle}`)

## 5) ข้อจำกัดข้อมูลที่ยังอยู่
- Lab มีสูงสุด 5 เดือนที่ประเมินได้ (มิ.ย.–ต.ค.) บน Production เหลือ 4 (ก.ค.–ต.ค.) จึงถึงสูงสุด Preliminary เกณฑ์ 6 เดือนทดสอบด้วย Fixture สังเคราะห์ที่ติดป้าย ไม่ลดเกณฑ์ ไม่สร้าง Actual/Shadow ย้อนหลัง
- มิถุนายนบน Production ไม่มี Shadow (Seal ก่อนมี MLOps) ไม่ย้อนสร้าง
- เดือนที่ Monitoring ล้มเหลว (เช่น ก.ย. ในเทส) ไม่ถูกคำนวณย้อนหลัง
