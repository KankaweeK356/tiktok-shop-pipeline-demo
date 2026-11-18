# UAT — Champion–Challenger Monitoring (revision 3)
| ชุดทดสอบ | ผล |
|---|---|
| Postgres journey Jan→Oct, DB ชั่วคราวในเครื่อง (21 เทส) | 21/21 PASS |
| MLOps unit (`test_mlops_monitoring.py`, `test_mlops_feature_store.py`) | 47/47 PASS |
| Node | 47/47 PASS |
| Python ที่เหลือ | 154 PASS · 7 FAIL (Legacy ล้มเหมือน baseline) · 3 skipped |
| ตรวจ SQL บน Neon Test Branch | 9 กรณี ดู NEON_DB_CHECKS_TH.md |
ใหม่ในรอบนี้: Recovery (Evaluation มีแต่ Summary ล้ม / ล้มก่อนเขียน / retry ไม่นับซ้ำ ไม่สร้าง Shadow ย้อนหลัง / Summary revision), Data Origin ต่อ Evaluation (ไม่รวมคนละแหล่ง), Security ชั้น 1–2, ML ไม่เป็น Official ทุกเส้นทาง, เพดาน Draft, ML request idempotent, concurrent writers
