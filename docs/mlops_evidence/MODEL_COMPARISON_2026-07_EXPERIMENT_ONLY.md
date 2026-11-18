# Model Comparison Report — เป้าหมาย 2026-07 (EXPERIMENT_ONLY)

- Training Run: `dfcd9bf4-ab14-4e97-bcdc-6825e82244e3`
- สถานะ Validation: **ELIGIBLE**
- ข้อมูลที่ใช้: 2026-01 → 2026-06 (6 เดือน), Feature `mlops-features-1`
- Walk-forward origins ที่ใช้เทียบเท่ากันทุกโมเดล: **3** (2026-03, 2026-04, 2026-05) · เกณฑ์ขั้นต่ำ 3

## ระดับการคำนวณ Metrics
- ระดับ Shop: รวมยอดคาดการณ์ของ 5 กลุ่มสินค้าเป็นยอดร้านต่อ origin แล้วเทียบกับยอดจริงของร้านเดือนนั้น WAPE = Σ|ผิดพลาดของร้าน| ÷ Σยอดจริงของร้าน, MAE = ค่าเฉลี่ย |ผิดพลาดของร้าน| ต่อ origin (บาท), Bias = ค่าเฉลี่ย (คาดการณ์ − จริง) ต่อ origin (บวก = คาดสูงเกิน)
- ระดับ Product Group: WAPE ของแต่ละกลุ่ม PG01–PG05 = Σ|คาดการณ์ − จริง| ÷ Σจริง ของกลุ่มนั้นทุก origin (ใช้ตรวจว่าโมเดลไม่ทำให้กลุ่มใดแย่ลง)

## 1) Validation (ย้อนหลัง · ระดับ Shop)

| โมเดล | บทบาท | origins | WAPE % | MAE ฿ | Bias ฿ | WAPE ต่างจาก Baseline (pp) | คาดการณ์เดือนเป้าหมาย ฿ |
|---|---|---|---|---|---|---|---|
| Baseline: ค่าเฉลี่ย 3 เดือนล่าสุด | BASELINE_OFFICIAL | 3 | 9.89 | 9,346 | -6,989 | 0.00 | 94,469.09 |
| Baseline: เท่าเดือนก่อน (naive) | BASELINE_REFERENCE | 3 | 12.56 | 11,861 | -4,502 | 2.66 | 104,725.06 |
| Ridge เดิม (ML ที่ใช้ในระบบ) | ML_OFFICIAL_CANDIDATE | 3 | 13.97 | 13,200 | -3,180 | 4.08 | 95,112.47 |
| Ridge + Marketing (ทดลอง) | ML_EXPERIMENTAL | 3 | 30.03 | 28,365 | 9,967 | 20.13 | 93,606.58 |

### WAPE รายกลุ่มสินค้า (ระดับ Product Group)

| โมเดล | PG01 | PG02 | PG03 | PG04 | PG05 |
|---|---|---|---|---|---|
| Baseline: ค่าเฉลี่ย 3 เดือนล่าสุด | 19.29 | 10.30 | 15.80 | 17.49 | 6.69 |
| Baseline: เท่าเดือนก่อน (naive) | 23.77 | 17.81 | 14.74 | 18.43 | 7.10 |
| Ridge เดิม (ML ที่ใช้ในระบบ) | 22.33 | 16.20 | 15.68 | 16.49 | 11.42 |
| Ridge + Marketing (ทดลอง) | 33.95 | 33.21 | 32.50 | 27.77 | 30.05 |

## 2) การเลือก Official Model
- ตัดสินโดย: monthly_forecast.generate_forecast (ตรรกะเดิม ไม่ถูกแก้)
- ผล: **BASELINE / trailing_3_month_mean** ยอดร้าน ฿94,469.09
- เหตุผล: BASELINE trailing_3_month_mean selected: ML challenger does not beat the baseline on the same 3 origins (ML shop WAPE 13.9729% vs 9.8931%)
- ML origins ที่ตรรกะเดิมนับ: 3 · สถานะ: OK
- Ridge + Marketing ไม่อยู่ในการเลือก Official

## 3) Forecast vs Actual (แยกจาก Validation)
- ยังไม่มียอดจริงของเดือนเป้าหมาย

> Validation = ผลย้อนหลังก่อนเดือนเป้าหมาย / Forecast vs Actual = เทียบยอดคาดการณ์กับยอดจริงหลังเดือนเป้าหมาย Publish แล้ว สองส่วนนี้ไม่นำมารวมหรือแทนกัน

## 4) ข้อจำกัด
- Walk-forward ที่ใช้เทียบทุกโมเดลมี 3 origin (2026-03, 2026-04, 2026-05) ต้องมีอย่างน้อย 3 จึงจะนับเป็น Eligible
- ข้อมูลจริงมีเพียง 6 เดือน × 5 กลุ่มสินค้า จึงมีแถวฝึกน้อยกว่าจำนวนตัวแปรของ Ridge + Marketing มาก ผลที่ได้ไม่ใช่หลักฐานเรื่องคุณภาพโมเดล
- ผลเปรียบเทียบเป็นผลย้อนหลัง (Validation) ไม่ใช่ความแม่นยำของ Forecast ที่จะเกิดขึ้นจริง
- Ridge + Marketing เป็น Challenger ทดลองเท่านั้น ไม่เข้ากระบวนการเลือก Official ไม่ว่าคะแนนจะเป็นอย่างไร
