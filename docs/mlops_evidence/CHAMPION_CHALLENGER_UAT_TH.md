# UAT — Champion–Challenger Monitoring (branch `claude/champion-challenger-monitoring`)

| ชุดทดสอบ | ผล |
|---|---|
| Postgres journey Jan→Oct + worker จริง (เทสข้อ 18: ประเมินอัตโนมัติ, pointer ผูก Forecast ที่ Seal, Shadow ก่อน Publish, Oracle อิสระตรวจ Cumulative WAPE, ฉีด error ที่ก.ย. แล้ว Publish ยัง SUCCESS, Historical/Experiment ไม่ถูกนับ, Forecast/Snapshot ไม่เปลี่ยน) | 18/18 ผ่าน |
| `test_mlops_monitoring.py` + `test_mlops_feature_store.py` (ขอบเกณฑ์ 2.00/1.98 จุด, 4 vs 3 จาก 6, 5.00/5.01 จุด, Evidence Level 0/2/3/5/6/9, Cumulative ≠ mean ของ WAPE รายเดือน, เหตุผลการไม่นับทุกรหัส, write-once, UI/API contract) | 30/30 ผ่าน |
| Node (รวม `fc=monitoring` อ่าน Artifact จริงจาก journey, cycle อื่นไม่เห็น, storage ล้ม = 503 แต่ `fc=status` ปกติ) | 40/40 ผ่าน |
| Python ที่เหลือ | 137 ผ่าน, 7 ล้ม = Legacy ชุดเดิมเป๊ะ (ล้มเหมือนกันบน baseline `pre-mlops-8f9d67f`; สาเหตุใน `UAT_RESULTS_TH.md`), 3 skipped |
| UI (Playwright, Artifact จริง) | ไม่มี JS error, ไม่มี horizontal scroll บนมือถือ; ตรวจสถานะ Empty / Preliminary (จริง) / Recommend และ Not-recommended (Fixture สังเคราะห์ ติดป้าย) |
