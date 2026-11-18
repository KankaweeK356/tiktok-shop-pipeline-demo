# Deployment Readiness, Smoke Test และ Rollback (ฉบับสุดท้าย — ยังไม่ merge / ไม่ deploy)

## 1) สถานะการทดสอบ
| ชุด | ผล |
|---|---|
| Postgres journey Jan→Oct (DB ชั่วคราวในเครื่อง ไม่ต่อ Neon) | 21/21 PASS (รวม 12b ML ถูกบล็อก+เพดาน Draft, 17 idempotent, 18 Monitoring, 19 concurrent, 20 Recovery) |
| MLOps unit | 47/47 PASS (Recovery, Data Origin, revision ของ Summary, นโยบาย ML) |
| Node (Security ชั้น 1–2, ไม่ leak secret) | 47/47 PASS |
| Python ที่เหลือ | 154 PASS, 7 FAIL = Legacy ชุดเดิมที่ล้มบน baseline `pre-mlops-8f9d67f`, 3 skipped |
| ตรวจ SQL บน Neon Test Branch (ผ่านเครื่องมือ Neon) | 9 กรณี PASS ดู `NEON_DB_CHECKS_TH.md` |

## 2) Public API (ไม่มี Login) — แต่ละชั้นกันอะไร
1. **Provenance ของ POST** (Origin / Sec-Fetch-Site): กัน CSRF และการยิงลวก ๆ ด้วย curl **ไม่ใช่ Authorization** (ปลอม header ได้)
2. **ตรวจฝั่ง Server + idempotency + เพดาน:** ตั๋วเซ็นด้วย admin key หมดอายุ 10 นาที, ตรวจ Cycle/Cutoff/Seal ในฐานข้อมูล, Draft ≤ 5/เดือน (API และ worker), simulate จำกัดขนาด, คำขอ ML ซ้ำคืนผลเดิม และ fail-closed ถ้าตรวจไม่ได้, Recovery ไม่ออกตั๋วถ้าไม่มีอะไรขาด
3. **Vercel Firewall rate limit:** ยังไม่ได้ตั้ง (ต้องแก้ค่าบน Vercel ซึ่งยังไม่อนุมัติ) ⇒ ข้อจำกัดที่ยอมรับสำหรับ Academic Demo
- Secret: ไม่มี secret ในโค้ด/Frontend; error ที่ส่งกลับเป็นรหัสเท่านั้น (มีเทสว่าไม่หลุด connection string/ชื่อ bucket)

## 3) ก่อน deploy (ต้องมีคนอนุมัติ/ทำ)
- [ ] ตรวจรับ Review Package นี้
- [ ] อนุมัติ merge
- [ ] ตั้ง `CLASSROOM_EVIDENCE_ORIGIN=PRODUCTION` บน Vercel Production (ถ้าไม่ตั้ง UI ถือเป็น `LAB_RUNTIME` ไม่แสดงแถบเตือน)
- [ ] (ไม่บังคับ) `CLASSROOM_MONITORING_STREAM` (ไม่ตั้ง = `lab-cycle-{cycle}`)
- [ ] (แนะนำ) ตั้ง Vercel Firewall rate limit บน `/api/lab-batch-result` และ `/api/lab-worker.py`
- [ ] (แนะนำ) เปลี่ยน/ลบ env เก่าของ branch `feature/classroom-demo-evidence-foundation` ที่ Vercel ติดธง `readable-secret` (3 ตัว) และ token GitHub เก่า
- [ ] ตรวจกับ Neon bucket จริง: PutObject, HEAD, ListObjectsV2 (หน้า Training Run ใช้ List; Monitoring ไม่ใช้) — ยังไม่ได้ยืนยัน (เครื่องที่ทดสอบเข้า Neon ตรงไม่ได้)

## 4) Smoke Test หลัง deploy (อ่านอย่างเดียว ไม่เขียน Production)
1. `GET /api/lab-batch-result?fc=status` → 200, `readiness`, `months[].published`
2. `GET ...?fc=forecast&month=2026-06` → Official เดิม: ยอดร้าน ฿89,967.41, `method_type=BASELINE`, hash ผลราย 5 กลุ่ม `bb54af72…0593` (เท่ากับ Before)
3. `GET ...?fc=mlops&month=2026-06` → 200 (ยังไม่มี run = ว่าง ไม่ error); ถ้า 503 = List ไม่รองรับ ให้แจ้ง
4. `GET ...?fc=monitoring` → 200, `summary:null`, `gaps:[]`
5. เปิดหน้า Forecast → ส่วนพับ ML Model & Experiment Details แสดงโดยไม่มี JS error
6. ตรวจ POST ไม่มี Origin (curl) ได้ 403 `ORIGIN_REQUIRED`
7. (เขียนข้อมูลจริง เช่น Generate กรกฎาคม ทำเมื่อพร้อมเดโมเท่านั้น และตรวจว่า `method_type=BASELINE`)

## 5) Rollback
- ไม่มี migration; ไฟล์ใหม่อยู่ใต้ `vercel-lab/ml/**` เท่านั้น → ไม่ต้องย้อนข้อมูล
- ย้อนด้วย Vercel: promote deployment เดิม (`dpl_HTsDXg8TTpqEpNenGx9B5dhH9x7d`, commit `8f9d67f`)
- ข้อควรระวังหลัง rollback: โค้ดเดิมเลือก ML เองได้ → ตรวจ `method_type` ของ Forecast ใหม่; ไฟล์ Artifact/Shadow ที่ค้างไม่กระทบ
- env ที่เพิ่ม (`CLASSROOM_EVIDENCE_ORIGIN`) ไม่มีผลกับโค้ดเดิม ลบทิ้งได้

## 6) ข้อจำกัดที่เหลือ (ยอมรับสำหรับ Academic Demo)
Lab ถึงสูงสุด Preliminary (Production 4 เดือน); มิถุนายนบน Production ไม่มี Shadow; write-once เป็นระดับแอป ไม่ใช่ Object Lock; ไม่มี rate limit ในโค้ด; ยังไม่ได้ Smoke กับ Neon Object Storage จริง
