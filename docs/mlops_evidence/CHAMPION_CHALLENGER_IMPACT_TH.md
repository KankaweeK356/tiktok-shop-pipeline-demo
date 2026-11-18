# Impact Assessment — Champion–Challenger Monitoring (branch `claude/champion-challenger-monitoring`)

ฐาน: `claude/mlops-feature-store` (a76afa8) · ยังไม่ merge · ไม่ deploy Production · ไม่ migration · ไม่แก้ข้อมูล Production

## 1) เกณฑ์ที่ล็อกและตำแหน่งในโค้ด (`pipeline/mlops/monitoring.py`)
| เกณฑ์ | การนำไปใช้ |
|---|---|
| Evidence Level: <3 Insufficient · 3–5 Preliminary · ≥6 Adequate | `evidence_level()` นับเฉพาะเดือนที่ **EVALUATED** |
| นับเฉพาะเดือนที่ Baseline และ ML มี Shadow ที่บันทึกก่อน Publish Actual และ Actual ครบ 5 กลุ่ม | `evaluate_month()` คืน `EXCLUDED` พร้อมรหัสเหตุผล: NO_SHADOW, SHADOW_NOT_BOUND_TO_SEALED_FORECAST, ML_OR_BASELINE_MISSING, SHADOW_NOT_RECORDED_BEFORE_ACTUAL, ACTUAL_INCOMPLETE, SHADOW_TARGET_MISMATCH, CUTOFF_MISMATCH (ไม่นับทั้งคู่) |
| Cumulative WAPE = Σ\|error\| ÷ Σ Actual ของเดือนชุดเดียวกัน | `summarize()` (มีเทสว่าไม่เท่าค่าเฉลี่ย WAPE รายเดือน และตรวจกับ Oracle อิสระใน Postgres journey) |
| ML ต่ำกว่า Baseline ≥ 2 จุด / Monthly APE ชนะ ≥ 4 จาก 6 เดือนล่าสุด / ไม่มีกลุ่มแย่กว่า > 5 จุด / ≥ 6 เดือน | 4 กฎใน `recommendation.rules` ทดสอบขอบเขต 2.00 / 1.98, 4 vs 3 ชนะ, 5.00 vs 5.01 จุด |
| แนะนำอย่างเดียว | `human_decision_required=true`, `auto_switch_champion=false`, `auto_retrain=false` |
| Ridge + Marketing | ไม่อยู่ในคู่หลัก (อยู่ใน Experiment Only เหมือนเดิม) |

สถานะที่แสดง: INSUFFICIENT_EVIDENCE · PRELIMINARY_NOT_ASSESSED (3–5 เดือน ตัวเลขแสดงแต่ยังไม่ตัดสินเกณฑ์) · RECOMMEND_REVIEW · NOT_RECOMMENDED (พร้อมเหตุผลรายข้อ)

## 2) สิ่งที่เพิ่ม/แก้
| ไฟล์ | การเปลี่ยน | ผลกระทบต่อของเดิม |
|---|---|---|
| `pipeline/mlops/training.py`, `definitions.py` | เพิ่ม `shadow_forecast.json` (Target Month, Created At, Data Cutoff, Feature Version, Model Version, คำทำนายราย 5 กลุ่ม + ยอดร้านของ Baseline/ML) และ pointer `monitoring/by_forecast/{forecast_id}.json` (เฉพาะ OFFICIAL_LINKED) ; เพิ่ม `model_version` ใน artifact Ridge | เพิ่มไฟล์ใหม่เท่านั้น Run เดิมไม่ถูกแก้ |
| `pipeline/mlops/monitoring.py` (ใหม่) | ตัวประเมิน + สรุป + บันทึกแบบ write-once | ไม่มีผลต่อ Forecast |
| `api/lab-worker.py` | hook `record_monitoring` หลัง `complete_run` ในขั้น Publish (ครอบ try/except แยก) | Publish ไม่ถูกกระทบ: ถ้าล้มจะรายงาน `monitoring.status=FAILED` เท่านั้น (ทดสอบด้วยการฉีด error ที่เดือนกันยายน) |
| `lib/lab-mlops.js`, `lib/lab-forecast.js` | `fc=monitoring` (อ่านอย่างเดียว) + ฟิลด์ `published` ใน `fc=status` | เพิ่มฟิลด์ใหม่ ไม่เปลี่ยนฟิลด์เดิม ไม่เพิ่ม Vercel Function |
| `dashboard/app.js`, `styles.css` | บล็อก Champion vs Challenger ในส่วนพับ ML เดิม (ไม่เพิ่ม Tab หลัก) | ส่วนอื่นของหน้าไม่เปลี่ยน |

ไม่แก้: Official Model Selection (`monthly_forecast.generate_forecast`), ER1/ER2, KPI, Published Actual, Forecast ที่ Seal, Scenario, schema ฐานข้อมูล (ไม่มี migration)

## 3) การเก็บและการป้องกันย้อนหลัง
- Storage: Neon Object Storage เดิม prefix `vercel-lab/ml/monitoring/{cycle}/…` (evaluations รายเดือน + summary `through=YYYY-MM.json` ไฟล์ใหม่ทุกเดือน) ทุกไฟล์ write-once (เนื้อหาต่างกัน = ปฏิเสธ)
- ไม่ต้องใช้สิทธิ์ List bucket สำหรับ Monitoring (ใช้ key ตายตัว)
- Shadow ที่นับต้องผูกกับ Forecast ID ที่ **Seal** (Draft ที่สร้างซ้ำไม่ถูกนับ) และ `created_at` ก่อนเวลา Publish Actual ใน Neon (`pipeline_runs.finished_at`)
- Historical Evaluation / Experiment ไม่มี pointer จึงถูกแยกโดยโครงสร้าง (มีเทสยืนยัน)
- ข้อจำกัดที่ต้องรู้: write-once บังคับที่ชั้นแอป ไม่ใช่ Object Lock ของ Storage; หลักฐานลำดับเวลามาจากเวลา Worker (Shadow) เทียบเวลาใน Neon (Publish)

## 4) ข้อขัดแย้งที่ต้องรายงานก่อนแก้ (ยังไม่ได้แก้)
**Model Selection เดิมเปลี่ยนเป็น ML ได้เองโดยอัตโนมัติ** ใน `generate_forecast`: เมื่อ walk-forward ≥ 3 origins และ ML ชนะ Baseline (margin 0 pp, กลุ่มแย่ลงไม่เกิน 5 pp) ระบบจะใช้ ML เป็น Official ทันที ซึ่งเกณฑ์ของนโยบายใหม่ (≥ 6 เดือนจริง, ต่ำกว่า ≥ 2 จุด, ชนะ ≥ 4/6, มนุษย์ตัดสิน) เข้มกว่ามาก
- ผลกระทบ: ตั้งแต่กรกฎาคมที่มี 3 origins Official อาจเป็น ML ก่อนที่ Monitoring จะมีหลักฐานจริง (ข้อมูลจริงตอนนี้ Baseline ชนะจึงยังเลือก Baseline)
- ที่ทำแล้ว: ไม่แก้ตามคำสั่ง; Monitoring เทียบ Baseline trailing 3 กับ Ridge คู่เดิมเสมอ และแสดงคำเตือนถ้ามีเดือนที่ Official เลือก ML (`official_ml_months`)
- ทางเลือกที่ขอให้ตัดสิน: (ก) คงเดิม + เตือน [ค่าเริ่มต้น] (ข) บังคับ Official = Baseline จนกว่าผู้ใช้อนุมัติ Champion Review (ต้องแก้ `generate_forecast`/Seal) (ค) ให้ ML เป็น Official ได้เมื่อ Monitoring ถึง RECOMMEND_REVIEW และมีมนุษย์อนุมัติเท่านั้น

## 5) ข้อจำกัดข้อมูล
- Production: มิถุนายน Seal ก่อนมี MLOps → ไม่มี Shadow ไม่ย้อนสร้าง เดือนแรกที่นับคือเดือนแรกที่ Generate หลัง deploy
- **ข้อค้นพบสำคัญ:** Source ของ Lab มีเดือนส่งมอบ 10 เดือน (ม.ค.–ต.ค.) และ Forecast ทางการเริ่มที่มิถุนายน จึงมีเดือนที่มี Actual ให้ประเมินได้สูงสุด **5 เดือน (มิ.ย.–ต.ค.)** และบน Production ที่มิถุนายน Seal ไปแล้วก่อนมี MLOps จะเหลือ **4 เดือน (ก.ค.–ต.ค.)** ดังนั้น **ระดับ Adequate (≥ 6 เดือน) และคำแนะนำ RECOMMEND_REVIEW ไม่สามารถเกิดขึ้นได้จาก Lab ชุดนี้** สูงสุดคือ Preliminary เกณฑ์ถูกต้องตามที่ล็อกและทดสอบด้วย Fixture แล้ว แต่ต้องมี Source เพิ่ม (เช่น พ.ย. ขึ้นไป) หรือข้อมูลจริงนอก Lab จึงจะถึง 6 เดือน — ขอให้พิจารณา
- เดือนที่ Monitoring ล้มเหลว (เช่น กันยายนในเทส) จะไม่ถูกคำนวณย้อนหลัง (เพื่อไม่ให้เกิดผลที่สร้างหลังรู้ Actual)
- Screenshot ใช้ Artifact จริงจาก Journey Jan→Oct บน Postgres ทดสอบ (ข้อมูล Final) ส่วนภาพ Adequate/Recommend ใช้ Fixture สังเคราะห์ (ระบุในภาพ/README) เพราะยังไม่มีเดือนจริงครบ 6
