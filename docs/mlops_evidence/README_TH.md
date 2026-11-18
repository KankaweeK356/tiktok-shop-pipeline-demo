# หลักฐาน MLOps รอบที่ 1–2 (Feature Store + Training Run) — MADT8102 Chapter 07

> สร้างจาก **Warehouse จริง** ที่ rebuild ในเครื่องจากไฟล์ Source Final เดียวกับ Production (แก้ SKU ของ March เหมือน Review & Fix)
> ยอดตรงกับ Production: มิ.ย. Net ฿104,725.06 · พ.ค. Ads ฿27,376.44 · ไม่มีข้อมูลสังเคราะห์ · ไม่ใช้ Expected KPI/QA เป็น feature
> ไฟล์ใน `sample_artifacts/` คือผลจริงของ 2 รัน (เขียนแบบ write-once ที่ path `vercel-lab/ml/...` เหมือนที่จะเกิดบน Neon Object Storage หลัง deploy)

## 1) Feature Store (Versioned Parquet)
- Path: `features/mlops-features-1/<source_run_id>/target=<เดือน>/` → `features.parquet`, `feature_definitions.json`, `manifest.json`
- หนึ่งแถวต่อ (origin month × กลุ่ม) · features ใช้เฉพาะข้อมูลเดือน ≤ origin · label = ยอดเดือนถัดไป · แถวสุดท้าย = inference ของเดือนเป้าหมาย (ไม่มี label)
- manifest เก็บ: feature_version, cutoff, source run, sha256 ของไฟล์ Warehouse, sha256 ของข้อมูลนำเข้า, สถิติ feature (mean/std/min/max/missing) สำหรับ drift, `point_in_time` (max known_at = 2026-05-31 สำหรับมิถุนายน)
- Marketing features (ใช้ในโมเดลทดลอง): `ads_to_gross_lag1`, `campaign_discount_to_gross_lag1` · เตรียมนิยามไว้แต่ยังไม่ใช้: `voucher_to_gross_lag1`, `affiliate_to_gross_lag1`, `net_trend_2m_pct`

## 2) Training Run (เก็บทุกโมเดลแม้ไม่ถูกเลือก)
`runs/<training_run_id>/` → `run.json`, `params.json`, `features_used.json`, `evaluation.json`, `status.json`, `models/{baseline_*, ridge_base, ridge_marketing}.json` + `index/<kind>/<เดือน>/<id>.json`

## 3) ผล Baseline vs ML (walk-forward รอบเดียวกัน)
### มิถุนายน 2569 — HISTORICAL_EVALUATION (ข้อมูลถึง พ.ค. เท่านั้น) — **Experimental — Insufficient Validation (2 รอบ < 3)**
| โมเดล | รอบ | WAPE | MAE | Bias (F−A) |
|---|---|---|---|---|
| Baseline trailing_3_month_mean | 2 | 7.43% | 6,640.11 | −3,104.30 |
| Baseline naive_previous_month | 2 | 8.22% | 7,339.73 | +3,699.13 |
| Ridge เดิม (ridge_base) | 2 | 12.11% | 10,823.53 | +4,206.83 |
| Ridge + Marketing (ทดลอง) | 2 | 32.18% | 28,749.36 | +28,749.36 |

- ตรรกะ Official ที่ไม่เปลี่ยน ให้ผล BASELINE trailing_3_month_mean **฿89,967.41** = Official Forecast ที่ Seal ไว้ (Golden proof) · รัน MLOps นี้ไม่ได้สร้าง Forecast นั้น
- Post-hoc (มิ.ย. Publish แล้ว ใช้ประเมินเท่านั้น): Actual ฿104,725.06 → error Baseline −14,757.65 (APE 14.09%), Ridge เดิม 17.14%, Ridge+Marketing 26.35%

### กรกฎาคม 2569 — EXPERIMENT_ONLY (ข้อมูลถึง มิ.ย.) — **ELIGIBLE (3 รอบ)**
| โมเดล | รอบ | WAPE | MAE | Bias (F−A) |
|---|---|---|---|---|
| Baseline trailing_3_month_mean | 3 | 9.89% | 9,345.96 | −6,988.76 |
| Baseline naive_previous_month | 3 | 12.56% | 11,860.94 | −4,501.70 |
| Ridge เดิม | 3 | 13.97% | 13,200.08 | −3,179.84 |
| Ridge + Marketing (ทดลอง) | 3 | 30.03% | 28,365.44 | +9,967.04 |

- ตรรกะ Official (ไม่เปลี่ยน) จะเลือก BASELINE ฿94,469.09 · ผลทดลองแยกจาก Official ชัดเจน (`kind=EXPERIMENT_ONLY`)

## 4) ข้อสรุปและข้อจำกัด (ตามจริง)
- ML ไม่ชนะ Baseline ทั้งสองเดือน และ **Ridge + Marketing แย่ที่สุด** (ตัวแปรมากกว่าข้อมูลมาก: ฝึกครั้งแรกมีไม่กี่แถว) จึงไม่ยกระดับเข้า Official
- มิถุนายนมีแค่ 2 รอบ ผลเป็นการทดลอง ไม่พิสูจน์คุณภาพโมเดล · กรกฎาคมมี 3 รอบพอดีเกณฑ์ขั้นต่ำ ยังเป็นตัวอย่างเล็กมาก
- ไม่ลดเกณฑ์ 3 รอบ ไม่ปรับคะแนน ไม่สร้างข้อมูลสังเคราะห์
- ไฟล์ตัวอย่างนี้สร้างในเครื่อง ยังไม่ได้เขียนลง Neon Object Storage ของ Production (ต้อง deploy ที่ได้รับอนุมัติ)
