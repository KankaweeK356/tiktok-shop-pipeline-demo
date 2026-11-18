# Model Comparison Report — เป้าหมาย 2026-06 (HISTORICAL_EVALUATION)

- Training Run: `5d90ada9-326a-4886-8b31-64a753a6b03b`
- สถานะ Validation: **EXPERIMENTAL_INSUFFICIENT_VALIDATION**
- ข้อมูลที่ใช้: 2026-01 → 2026-05 (5 เดือน), Feature `mlops-features-1`
- Walk-forward origins ที่ใช้เทียบเท่ากันทุกโมเดล: **2** (2026-03, 2026-04) · เกณฑ์ขั้นต่ำ 3

## ระดับการคำนวณ Metrics
- ระดับ Shop: รวมยอดคาดการณ์ของ 5 กลุ่มสินค้าเป็นยอดร้านต่อ origin แล้วเทียบกับยอดจริงของร้านเดือนนั้น WAPE = Σ|ผิดพลาดของร้าน| ÷ Σยอดจริงของร้าน, MAE = ค่าเฉลี่ย |ผิดพลาดของร้าน| ต่อ origin (บาท), Bias = ค่าเฉลี่ย (คาดการณ์ − จริง) ต่อ origin (บวก = คาดสูงเกิน)
- ระดับ Product Group: WAPE ของแต่ละกลุ่ม PG01–PG05 = Σ|คาดการณ์ − จริง| ÷ Σจริง ของกลุ่มนั้นทุก origin (ใช้ตรวจว่าโมเดลไม่ทำให้กลุ่มใดแย่ลง)

## 1) Validation (ย้อนหลัง · ระดับ Shop)

| โมเดล | บทบาท | origins | WAPE % | MAE ฿ | Bias ฿ | WAPE ต่างจาก Baseline (pp) | คาดการณ์เดือนเป้าหมาย ฿ |
|---|---|---|---|---|---|---|---|
| Baseline: ค่าเฉลี่ย 3 เดือนล่าสุด | BASELINE_OFFICIAL | 2 | 7.43 | 6,640 | -3,104 | 0.00 | 89,967.41 |
| Baseline: เท่าเดือนก่อน (naive) | BASELINE_REFERENCE | 2 | 8.22 | 7,340 | 3,699 | 0.78 | 83,821.69 |
| Ridge เดิม (ML ที่ใช้ในระบบ) | ML_OFFICIAL_CANDIDATE | 2 | 12.11 | 10,824 | 4,207 | 4.68 | 86,771.87 |
| Ridge + Marketing (ทดลอง) | ML_EXPERIMENTAL | 2 | 32.18 | 28,749 | 28,749 | 24.75 | 77,127.46 |

### WAPE รายกลุ่มสินค้า (ระดับ Product Group)

| โมเดล | PG01 | PG02 | PG03 | PG04 | PG05 |
|---|---|---|---|---|---|
| Baseline: ค่าเฉลี่ย 3 เดือนล่าสุด | 19.60 | 3.52 | 6.90 | 21.93 | 4.54 |
| Baseline: เท่าเดือนก่อน (naive) | 17.60 | 10.49 | 8.30 | 24.43 | 8.76 |
| Ridge เดิม (ML ที่ใช้ในระบบ) | 21.31 | 9.31 | 6.83 | 21.94 | 13.54 |
| Ridge + Marketing (ทดลอง) | 37.14 | 31.23 | 29.88 | 29.73 | 42.89 |

## 2) การเลือก Official Model
- ตัดสินโดย: monthly_forecast.generate_forecast (ตรรกะเดิม ไม่ถูกแก้)
- ผล: **BASELINE / trailing_3_month_mean** ยอดร้าน ฿89,967.41
- เหตุผล: INSUFFICIENT_VALIDATION: only 2 valid walk-forward origin(s) for the ML challenger (need 3); official forecast uses BASELINE trailing_3_month_mean
- ML origins ที่ตรรกะเดิมนับ: 2 · สถานะ: INSUFFICIENT_VALIDATION
- Ridge + Marketing ไม่อยู่ในการเลือก Official

## 3) Forecast vs Actual (แยกจาก Validation)
- POST_HOC_EVALUATION (the target month was already published; used only for evaluation, never as a feature)
- ยอดจริงของร้าน ฿104,725.06

| โมเดล | คาดการณ์ ฿ | APE % |
|---|---|---|
| Baseline: เท่าเดือนก่อน (naive) | 83,821.69 | 19.96 |
| Baseline: ค่าเฉลี่ย 3 เดือนล่าสุด | 89,967.41 | 14.09 |
| Ridge เดิม (ML ที่ใช้ในระบบ) | 86,771.87 | 17.14 |
| Ridge + Marketing (ทดลอง) | 77,127.46 | 26.35 |

> Validation = ผลย้อนหลังก่อนเดือนเป้าหมาย / Forecast vs Actual = เทียบยอดคาดการณ์กับยอดจริงหลังเดือนเป้าหมาย Publish แล้ว สองส่วนนี้ไม่นำมารวมหรือแทนกัน

## 4) ข้อจำกัด
- สถานะ Experimental / Insufficient Validation: origin น้อยกว่าเกณฑ์ ห้ามใช้ผลนี้ตัดสินเลือกโมเดล
- Walk-forward ที่ใช้เทียบทุกโมเดลมี 2 origin (2026-03, 2026-04) ต้องมีอย่างน้อย 3 จึงจะนับเป็น Eligible
- ข้อมูลจริงมีเพียง 5 เดือน × 5 กลุ่มสินค้า จึงมีแถวฝึกน้อยกว่าจำนวนตัวแปรของ Ridge + Marketing มาก ผลที่ได้ไม่ใช่หลักฐานเรื่องคุณภาพโมเดล
- ผลเปรียบเทียบเป็นผลย้อนหลัง (Validation) ไม่ใช่ความแม่นยำของ Forecast ที่จะเกิดขึ้นจริง
- Ridge + Marketing เป็น Challenger ทดลองเท่านั้น ไม่เข้ากระบวนการเลือก Official ไม่ว่าคะแนนจะเป็นอย่างไร
