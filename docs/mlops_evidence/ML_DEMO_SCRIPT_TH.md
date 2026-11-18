# สคริปต์สาธิต ML (ประมาณ 6–8 นาที): Feature → Training → Walk-forward → Comparison → Monitoring → Decision
เปิดหน้า **คาดการณ์และวางแผน** → เลือกเดือน **มิถุนายน 2569** → กางส่วนพับ **ML Model & Experiment Details** (บาร์ 8 ขั้นด้านบนคือสายงานทั้งหมด)

**ป้ายที่ต้องพูดทุกครั้ง:** ตัวเลขจากข้อมูล Source จริงที่รันในเครื่อง = *Real-source Test* (ไม่ใช่ Production) · กรณี 6 เดือนที่ Lab ถึงไม่ได้ = *Synthetic Fixture* (สังเคราะห์ ไม่ใช่ผลจริง) UI แสดงแถบเตือนสีเหลืองให้เองเมื่อเป็นสองประเภทนี้

| ขั้น | คลิก/ชี้ | พูดอะไร | หลักฐาน |
|---|---|---|---|
| 1 Feature | แท็บ Historical Evaluation → ขั้น ② Feature Store ในบาร์ ; รายการไฟล์ | Feature แบบ point-in-time (ใช้ข้อมูลถึงเดือนก่อนเท่านั้น), เก็บเป็น Parquet เวอร์ชันเดียว ไม่เขียนทับ, ตรวจครบ 5 กลุ่มทุกเดือนก่อนทำนาย | `features.parquet`, `manifest.json` (no_future_rows) |
| 2 Training | ขั้น ③ Training ; ตาราง 4 โมเดล | เทรน Baseline 2 แบบ + Ridge + Ridge+Marketing (ทดลอง) เก็บพารามิเตอร์/โมเดลทุกตัว แม้ ML ไม่ถูกเลือก | `runs/<id>/models/*.json`, `params.json` |
| 3 Walk-forward | ① Validation (ระดับ Shop) + รายกลุ่ม | มิถุนายนมี 2 origin ต่ำกว่าเกณฑ์ 3 จึง **Experimental/Insufficient Validation** เทียบทุกโมเดลบน origin เดียวกัน: Baseline 7.43% · Ridge 12.11% · Ridge+Marketing 32.18% | `evaluation.json` |
| 4 Comparison | ② การเลือก Official + ③ Forecast vs Actual | Official ใช้ Baseline (฿89,967.41) เลือกโดยตรรกะเดิม; ML ไม่เป็น Official อัตโนมัติ; ยอดจริงมิ.ย. ฿104,725.06 แยกจาก Validation | `report.json` |
| 5 Monitoring | บล็อก Champion vs Challenger (Real-source Test 5 เดือน) | Shadow Forecast บันทึกก่อน Publish Actual ทุกเดือน; Baseline 11.18% vs Ridge 13.06%; ระดับ Preliminary; เดือนที่ไม่นับแสดงพร้อมเหตุผล | `monitoring/…/summary/through=2026-10.rev1.json` |
| 6 Decision | ขั้น ⑧ Decision ในบาร์ + การ์ดคำแนะนำ | ยังไม่ผ่านเกณฑ์ (ต้อง ≥6 เดือน, ลด WAPE ≥2 จุด, ชนะ ≥4 จาก 6, กลุ่มไม่แย่เกิน 5 จุด) ระบบแนะนำเท่านั้น **ไม่มีฟังก์ชันเปลี่ยน Champion และไม่ Retrain เอง** | rules ในการ์ด |
| (ถ้าอาจารย์ถามกรณีผ่านเกณฑ์) | เปิดภาพ `SYNTHETIC_FIXTURE_fixture_recommend.png` | นี่คือข้อมูลสังเคราะห์เพื่อพิสูจน์กฎ RECOMMEND_REVIEW; Lab จริงถึงสูงสุด 5 เดือน | `synthetic_fixtures/` |
| กรกฎาคม (เสริม MLOps) | เลือกกรกฎาคม → Experiment Only | 3 origin = Eligible แต่ยังเป็นการทดลอง ไม่ใช่ Official | `MODEL_COMPARISON_2026-07_EXPERIMENT_ONLY.md` |

**ถ้ามีคนถาม:** "ทำไม ML แพ้" → ข้อมูลมีแค่ 5–6 เดือน × 5 กลุ่ม แถวฝึกน้อยกว่าจำนวนตัวแปรมาก ไม่ได้ปรับเกณฑ์ให้ ML ชนะ · "ผลนี้คือ Production ไหม" → ไม่ใช่ เป็น Real-source Test ในเครื่อง (ยังไม่ deploy)
