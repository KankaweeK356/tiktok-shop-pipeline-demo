# UAT — Champion–Challenger Monitoring (revision 2)

| ชุดทดสอบ | ผล |
|---|---|
| Postgres journey Jan→Oct + worker จริง (20 เทส) — ใหม่: 12b (ML ถูกบล็อกทุกเส้นทาง, ฉีดผล ML แล้วไม่มีอะไรถูกเขียน), 18 (Monitoring อัตโนมัติ/ก่อน Publish/Champion = Official ที่ Seal/Oracle อิสระ/มิถุนายนเดิมไม่เปลี่ยน/ไม่มีแถว ML), 19 (concurrent writers) | 20/20 ผ่าน |
| MLOps unit/contract (`test_mlops_monitoring.py`, `test_mlops_feature_store.py`) | 40/40 ผ่าน |
| Node (รวม stream, ข้ามปี, data_origin, storage ล้ม = 503) | 41/41 ผ่าน |
| Python ที่เหลือ | ดู `UAT_REGRESSION_TH.md` |
| UI (Playwright) | ไม่มี JS error; แถบเตือนข้อมูลสังเคราะห์/ทดสอบแสดงถูกต้อง; ไม่มี horizontal scroll บนมือถือ |

ไฟล์ Evidence: `local_real_source_test/` (ข้อมูล Source จริง, DB ชั่วคราว, ไม่ใช่ Production) แยกจาก `synthetic_fixtures/` (สังเคราะห์) — ยังไม่มี Production evidence
