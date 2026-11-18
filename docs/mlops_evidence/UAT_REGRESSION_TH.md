# Regression — ก่อน Deploy (branch `claude/champion-challenger-monitoring`, commit หลังจาก 90e35d4)

| ชุด | ผล |
|---|---|
| Postgres journey Jan→Oct + worker จริง | 20/20 ผ่าน |
| Python (ไม่รวมไฟล์ Postgres) | 147 ผ่าน · 7 ล้ม (Legacy) · 3 skipped |
| Node | 41/41 ผ่าน |

7 Legacy failing tests = ชุดเดียวกับที่ล้มบน baseline `pre-mlops-8f9d67f` (ก่อนเริ่มงาน MLOps) ทุกข้อ: เทสตรวจ "ข้อความซอร์สเก่า" ที่ถูกรื้อไปแล้ว
test_pipeline_lab (2): `state.labResults[def.id]=payload`, `current.protection_pct/status` · test_real_lab (5): `complete_run(db_url`, label เก่าใน app.js, `CLASSROOM_GITHUB_TOKEN` / `CLASSROOM_LAB_NEON_URL` ใน api/lab-batch.js, เงื่อนไข phase ใน api/lab-reset.js
งานนี้ไม่ได้แก้ api/lab-batch.js, api/lab-reset.js หรือ pipeline เดิม
