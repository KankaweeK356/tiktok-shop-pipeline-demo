# ตรวจฐานข้อมูลผ่านเครื่องมือ Neon (Test Branch `smoke-mlops-20261118`; Production = SELECT อย่างเดียว)
| # | กรณี | Expected | Actual | ผล |
|---|---|---|---|---|
| 1 | Test Branch = สำเนา Production (cycle 39) | Publish Jan–Jun 6 รอบ | initial, incremental_01..05 ครบ | PASS |
| 2 | SQL ดึงเดือนที่ Publish (hook/Recovery) | ทำงานบน schema จริง | ทำงานได้ | PASS |
| 3 | SQL ดึง Official ที่ Seal + นับ Draft | Official มิ.ย. 5 กลุ่ม | Forecast e86a07aa… ครบ, drafts=0 | PASS |
| 4 | Official มิ.ย. บน Test Branch | hash bb54af72…0593 | ตรง | PASS |
| 5 | Advisory lock | ทำงาน | true | PASS |
| 6 | ไม่มี ML ในฐานข้อมูล | BASELINE เท่านั้น | BASELINE | PASS |
| 7 | Production After-hash Official มิ.ย. | = Before (bb54af72…0593, ฿89,967.41, Seal 2026-11-18T15:35:53Z) | ตรงทุกค่า | PASS |
| 8 | Production forecast_run ไม่เปลี่ยน | 8 แถว | 8 แถว (pipeline_runs ไม่ได้เก็บ Before) | PASS บางส่วน |
| 9 | Bucket Test Branch แยกและว่าง | ไม่มี object | ว่าง; endpoint เป็นของ branch ตัวเอง | PASS |
ไม่มีการเขียนบน Production. ทรัพยากรที่สร้าง: branch `smoke-mlops-20261118` (br-noisy-pine-be1aorel), bucket `smoke-mlops-lake` (private), credential `smoke-mlops-20261118` (หมดอายุ 2026-11-25) — ยังไม่ลบ รอคำสั่ง
ไม่ได้ทำ: รัน worker/API กับ Neon จริง (เครื่องทดสอบเข้า Neon ตรงไม่ได้), listing Storage Production (หา bucket ไม่เจอผ่านเครื่องมือ)
