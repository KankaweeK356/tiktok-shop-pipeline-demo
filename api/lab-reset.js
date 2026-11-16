/** Clear only the isolated classroom live-run Neon lab, atomically. */
import sourceContract from "../dashboard/data/classroom_source_contract.json" with { type: "json" };
import { getNeonSql } from "../lib/neon-router.js";

const DERIVED = ["Fact_Inventory_Snapshot", "Fact_Stock_Movement",
  "Fact_Order_Platform_Fees", "Fact_FIFO_Allocation"];
const TABLES = [...DERIVED, ...sourceContract.source_tables.slice().reverse()];

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  if (!["GET", "POST"].includes(req.method)) return res.status(405).json({ error: "GET/POST only" });
  let sql;
  try { sql = getNeonSql("live"); }
  catch (_error) { return res.status(503).json({ error: "เชื่อมต่อ Neon Lab ไม่ได้" }); }

  if (req.method === "GET") {
    const requested = Number(req.query?.cycle);
    if (!Number.isInteger(requested) || requested < 1) return res.status(400).json({ error: "Cycle ไม่ถูกต้อง" });
    try {
      const rows = await sql.query("SELECT phase,cycle_number FROM demo_control.dataset_state WHERE dataset_key='classroom'");
      if (!rows.length) return res.status(503).json({ found: false, error: "ไม่พบสถานะ Lab ใน Neon" });
      const row = rows[0];
      const cleared = Number(row.cycle_number) > requested && row.phase === "EMPTY";
      return res.status(200).json({ found: cleared, status: cleared ? "completed" : "in_progress",
        conclusion: cleared ? "success" : null, cycle: Number(row.cycle_number), phase: row.phase });
    } catch (_error) { return res.status(503).json({ found: false, error: "อ่านสถานะการเคลียร์จาก Neon ไม่ได้" }); }
  }

  let body = req.body || {};
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch (_error) { return res.status(400).json({ error: "ข้อมูลคำขอไม่ถูกต้อง" }); }
  }
  const expected = Number(body.expected_cycle);
  if (body.confirmation !== "RESET-DEMO-DATA" || !Number.isInteger(expected) || expected < 1)
    return res.status(400).json({ error: "คำขอเคลียร์ Lab ไม่ครบหรือ Cycle ไม่ถูกต้อง" });

  try {
    const deletions = TABLES.map(name => `DELETE FROM demo_er1."${name}";`).join("\n");
    // One PostgreSQL DO block is one transaction: any table, state or audit failure rolls it all back.
    await sql.query(`DO $classroom_reset$
      DECLARE current_cycle integer; active_count integer;
      BEGIN
        SELECT cycle_number INTO current_cycle FROM demo_control.dataset_state
          WHERE dataset_key='classroom' FOR UPDATE;
        IF current_cycle IS NULL OR current_cycle <> ${expected} THEN
          RAISE EXCEPTION 'CYCLE_CHANGED';
        END IF;
        SELECT COUNT(*) INTO active_count FROM demo_control.pipeline_runs
          WHERE dataset_key='classroom' AND cycle_number=current_cycle AND status IN ('RUNNING','QUEUED');
        IF active_count > 0 THEN RAISE EXCEPTION 'RUN_IN_PROGRESS'; END IF;
        ${deletions}
        UPDATE demo_control.dataset_state SET phase='EMPTY',cycle_number=current_cycle+1,
          last_run_id=NULL,lock_version=lock_version+1,updated_at=now()
          WHERE dataset_key='classroom';
        INSERT INTO demo_control.reset_audit
          (dataset_key,previous_cycle,next_cycle,actor,reason,data_tables_cleared,status)
          VALUES ('classroom',current_cycle,current_cycle+1,'vercel-dashboard-operator',
          'Operator requested classroom lab reset',${TABLES.length},'SUCCEEDED');
      END $classroom_reset$;`);

    const state = await sql.query("SELECT phase,cycle_number FROM demo_control.dataset_state WHERE dataset_key='classroom'");
    const counts = await Promise.all(TABLES.map(async name => {
      const result = await sql.query(`SELECT COUNT(*)::int AS n FROM demo_er1."${name}"`);
      return { table: name, rows: Number(result[0]?.n ?? -1) };
    }));
    const remaining = counts.filter(row => row.rows !== 0);
    if (state[0]?.phase !== "EMPTY" || remaining.length)
      return res.status(503).json({ cleared: false, cycle: Number(state[0]?.cycle_number),
        error: "Neon ยังยืนยันไม่ได้ว่าทุกตารางว่าง กรุณาตรวจสอบสถานะก่อนเริ่ม Run ใหม่" });
    return res.status(200).json({ accepted: true, cleared: true, status: "SUCCEEDED",
      cycle: Number(state[0].cycle_number), tables_cleared: counts.length, remaining_rows: 0,
      execution_engine: "VERCEL_NATIVE" });
  } catch (error) {
    const message = String(error?.message || "");
    if (message.includes("RUN_IN_PROGRESS")) return res.status(409).json({ error: "มี Run กำลังทำงานอยู่ เคลียร์ไม่ได้" });
    if (message.includes("CYCLE_CHANGED")) return res.status(409).json({ error: "สถานะ Lab เปลี่ยนแล้ว กรุณาโหลดหน้าใหม่ก่อนเคลียร์" });
    console.error("Classroom lab reset failed:", error?.name || "unknown");
    return res.status(503).json({ cleared: false, error: "เคลียร์ไม่สำเร็จ ระบบย้อนการเปลี่ยนแปลงแล้ว กรุณาตรวจสถานะ Neon" });
  }
}
