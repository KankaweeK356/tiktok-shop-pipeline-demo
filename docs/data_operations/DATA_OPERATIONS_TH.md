# Data Operations Dashboard — Audit, Decision, Implementation, Test (Branch: `claude/data-operations-dashboard`)

ไม่มี Merge / Deploy Production · ไม่แตะ Neon / Env / Schema ER1–ER2 / สูตร KPI / Forecast / Model

## A. Existing System Assessment (Gap Assessment)
| ความต้องการ | สถานะ | หลักฐานในระบบจริง | การดำเนินการ |
|---|---|---|---|
| Pipeline Run ต่อเดือน, Run ID, สถานะ | EXISTING | `/api/lab-batch` → `months[]`, `current_cycle_runs[]` (จาก `demo_control.pipeline_runs`) | REUSE |
| Chip 10 เดือน + ปุ่ม Run | EXISTING | `renderPipeline()` month chips, Run This Month | ไม่แตะ |
| 5 ขั้นตอน + Preview/Input/Process/Validation/Output | EXISTING | `NOTEBOOK_STAGES` | ไม่แตะ |
| DQ Review & Fix / Revalidate / Resume | EXISTING | `renderDqRecovery`, `/api/lab-batch-result?dq=` | REUSE (ลิงก์ไป) |
| Published Snapshot / published_through | EXISTING ที่ API แต่ **ไม่เคยแสดง** | `published_snapshots[]`, `published_through` | IMPROVE (เก็บเข้า state + แสดง) |
| Data Lake & Warehouse explorer, Neon explorer | EXISTING | tab 2–3 | REUSE (ลิงก์ไป) |
| ML Monitoring (evidence level, gaps) | EXISTING | `?fc=monitoring` | REUSE (สรุป + ลิงก์) |
| **สรุปสุขภาพ Pipeline ในที่เดียว** (Running/Ready/Failed/Blocked/Completed, Published N/10, DQ, Warehouse, Action required) | **MISSING** | ผู้ดูแลต้องไล่ดูหลายส่วน | เพิ่ม (Overview) |
| ตารางสถานะรายเดือนแบบอ่านทีเดียว | MISSING | มีแต่ chip | เพิ่ม (ใช้ข้อมูลเดิม) |
| Error ระบบ (non-DQ) แยกจาก DQ | IMPROVE | `latest_failed_run` ไม่แสดงสรุป | เพิ่มในส่วน C |
| Warehouse readiness + กฎ "Pipeline สำเร็จ ≠ KPI PASS", Staging ≠ Published | MISSING | — | เพิ่มในส่วน D |
| จำนวนแถวต่อขั้นตอน | NOT REQUIRED (ซ้ำ) | มีใน Validation/Output ของแต่ละขั้น | ไม่ทำซ้ำ (ไม่แสดงเลขที่ API ไม่ส่ง) |

## B. Architecture Decision
**Option A** — เพิ่ม "Data Operations Overview" ที่หัวหน้า Data Pipeline Runner (ไม่เพิ่มแท็บ/เมนู/API/ตาราง/Infrastructure) เหตุผล: ข้อมูลทั้งหมดมีใน `/api/lab-batch` อยู่แล้ว; ผู้ดูแลเห็นสถานะและกดแก้ในหน้าเดียวกัน. Logic สรุปแยกเป็นฟังก์ชันบริสุทธิ์ `PipelineState.monthRows/opsOverview` (ทดสอบด้วย `node --test`).

## C. Implementation (เฉพาะ Gap)
- `dashboard/pipeline-state.js`: `monthRows`, `opsOverview` (ไม่รู้ = `NOT_VERIFIED`, ไม่ใช่ 0/PASS)
- `dashboard/app.js`: เก็บ `published_snapshots`/`published_through`; `renderOpsOverview` (A สรุป+Action required+รายละเอียดเทคนิคพับได้, B รายเดือน, C DQ/Error, D Warehouse+Lineage, E ML สรุป) เรียกก่อน Source Selector; ปุ่ม "ไปที่ Review & Fix" เปิด Drawer เดิม
- `dashboard/styles.css`: สไตล์ `ops-*` (สี + ข้อความ, Responsive)
- ไม่มีการเปลี่ยน API, DB, Worker, ER1/ER2, Forecast, ML

กติกาสถานะ: Running > Blocked(DQ) > Failed(system) > Completed(10/10) > Ready > Waiting; DQ: Failed=มีเดือนบล็อกและยังไม่แก้, Pending=READY_TO_RESUME, Passed=มีเดือน Published และไม่มีบล็อก, Not Checked=ยังไม่รัน, NOT VERIFIED=Migration/API อ่านไม่ได้; Warehouse: Published ต้องมี snapshot จาก API.

## D. Test Evidence
- Unit: `node --test tests/js/*.test.mjs` → **57/57 PASS** (เพิ่ม 8 กรณี: not loaded, ready, March blocked, pending, system failed, running, snapshot missing/0/10 เดือน, fallback)
- UI (Playwright + mock Backend รูปแบบเดียวกับ API จริง, `tests/integration/ops_overview_harness.mjs`; ML ใช้ Artifact จริงจาก Fixture local): ภาพใน `screenshots/`
| UAT | ผล |
|---|---|
| 1 Overview ตรงกับ backend (Published 2/10, Blocked, DQ Failed) | PASS |
| 2 March DQ error → ปุ่ม Review & Fix เปิด Drawer เดิม | PASS |
| 3 รีเฟรชแล้วสถานะเดิม | PASS |
| 4 Failed/Blocked ไม่แสดง March เป็น Published (Published 2/10; Warehouse ถึง ก.พ.) | PASS |
| 5 System failure แยกจาก DQ (Failed + Retry, DQ=Passed) | PASS |
| 6 ML monitoring ล่ม → "NOT AVAILABLE ไม่ได้แปลว่าผ่าน/ไม่ผ่าน" | PASS |
| 7 API หลักล่ม → NOT VERIFIED ไม่แสดงเลข | PASS |
| 8 Runner เดิม (ปุ่ม Run, 10 chip, 5 ขั้น, DQ drawer) ยังอยู่ | PASS |
| 9 Mobile 390px: ส่วน Overview ไม่ล้นจอ | PASS (หน้าเดิมมี overflow 409/390 จากแถบ nav/tab ที่มีอยู่เดิม ไม่ใช่ส่วนใหม่) |
| 10 Business Dashboard/Forecast/Scenario ไม่เปลี่ยน | PASS (ไม่แก้ไฟล์/โค้ดที่เกี่ยว) |

ข้อจำกัด: ทดสอบกับ mock backend ไม่ใช่ Neon/Production; "Reconciliation" แสดงได้เฉพาะเมื่อโหลดหลักฐานขั้น Validate ไว้แล้ว (มิฉะนั้น NOT VERIFIED); ไม่มีจำนวนแถวต่อขั้นใน Overview; ยังไม่ Deploy.

## E. Rubric Mapping
| Dashboard | ผู้ใช้ | คำถามที่ตอบ | ที่อยู่ |
|---|---|---|---|
| 1 Business Owner | เจ้าของร้าน | ยอดขาย/KPI/Forecast/Scenario | ภาพรวมธุรกิจ, พยากรณ์และวางแผน, Forecast vs Actual |
| 2 Data Operations | ผู้ดูแลข้อมูล | Pipeline ถึงไหน/DQ/Warehouse พร้อมไหม/ML trace | Test Pipeline → Data Operations Overview |
ทั้งสองอ่านข้อมูลชุดเดียวกัน: Pipeline เขียน ER1→Lake→ER2 และ Publish Snapshot; Business Dashboard ใช้เฉพาะเดือน Published.
Rubric: Data Sources / DB-Warehouse / ETL (Runner 5 ขั้น) · Dashboards ≥2 role (ข้างบน) · AI/ML (E + หน้า Forecast) · Storytelling (Overview → Review & Fix → Publish → KPI).
