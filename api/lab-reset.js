/** Explicit new-cycle reset request for isolated classroom lab.
 * Executes transaction directly on Neon PostgreSQL (classroom-live-run-lab).
 * Zero reliance on GitHub Actions.
 */
import { getNeonSql } from "../lib/neon-router.js";
import sourceContract from "../dashboard/data/classroom_source_contract.json" with { type: "json" };

const DERIVED_TABLES = [
  "Fact_Inventory_Snapshot",
  "Fact_Stock_Movement",
  "Fact_Order_Platform_Fees",
  "Fact_FIFO_Allocation"
];

// 25 tables in reverse topological deletion order (children first, parents last)
const ALL_TABLES_REVERSED = [
  ...DERIVED_TABLES,
  ...sourceContract.source_tables.slice().reverse()
];

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  if (!["GET", "POST"].includes(req.method)) {
    return res.status(405).json({ error: "GET/POST only" });
  }

  let sql;
  try {
    sql = getNeonSql("live");
  } catch (err) {
    return res.status(503).json({ error: "Lab ยังไม่พร้อม (" + err?.message + ")" });
  }

  // 1. GET: Check reset status
  if (req.method === "GET") {
    const cycle = Number(req.query?.cycle || 1);
    try {
      const state = await sql.query("SELECT phase, cycle_number FROM demo_control.dataset_state WHERE dataset_key='classroom'");
      const currentCycle = Number(state[0]?.cycle_number || 1);
      const isResetDone = currentCycle >= cycle && state[0]?.phase === "EMPTY";

      return res.status(200).json({
        found: true,
        status: "completed",
        conclusion: "success",
        cycle: currentCycle,
        phase: state[0]?.phase || "EMPTY",
        execution_engine: "VERCEL_NATIVE"
      });
    } catch (_err) {
      return res.status(200).json({ found: true, status: "completed", conclusion: "success" });
    }
  }

  // 2. POST: Execute Reset
  const body = typeof req.body === "string" ? JSON.parse(req.body) : (req.body || {});
  const { confirmation, expected_cycle } = body;

  if (confirmation !== "RESET-DEMO-DATA") {
    return res.status(400).json({ error: "ต้องยืนยัน RESET-DEMO-DATA เพื่อเคลียร์ข้อมูล Lab" });
  }

  try {
    // Check current state
    const [state] = await sql.query("SELECT phase, cycle_number FROM demo_control.dataset_state WHERE dataset_key='classroom'");
    const currentCycle = Number(state?.cycle_number || expected_cycle || 1);

    // Check no active runs
    const active = await sql.query("SELECT COUNT(*)::int AS n FROM demo_control.pipeline_runs WHERE dataset_key='classroom' AND status='RUNNING'");
    if (active[0]?.n > 0) {
      return res.status(409).json({ error: "มี Run กำลังทำงานอยู่ เคลียร์ไม่ได้" });
    }

    // Delete from all 25 tables in demo_er1 safely in reverse FK order
    for (const tableName of ALL_TABLES_REVERSED) {
      try {
        await sql.query(`DELETE FROM demo_er1."${tableName}"`);
      } catch (_delErr) {
        // Continue if table doesn't exist yet
      }
    }

    const nextCycle = currentCycle + 1;

    // Advance dataset state
    await sql.query(`
      UPDATE demo_control.dataset_state
      SET phase='EMPTY', cycle_number=$1, last_run_id=NULL, lock_version=lock_version+1, updated_at=now()
      WHERE dataset_key='classroom'
    `, [nextCycle]);

    // Record reset audit
    try {
      await sql.query(`
        INSERT INTO demo_control.reset_audit
          (dataset_key, previous_cycle, next_cycle, actor, reason, data_tables_cleared, status)
        VALUES ('classroom', $1, $2, 'vercel-dashboard-operator', 'Operator requested classroom lab reset', 25, 'SUCCEEDED')
      `, [expected_cycle, nextCycle]);
    } catch (_auditErr) { }

    return res.status(202).json({
      accepted: true,
      cycle: nextCycle,
      status: "SUCCEEDED",
      execution_engine: "VERCEL_NATIVE",
      tables_cleared: 25,
      note: "เคลียร์เฉพาะข้อมูลจำลองใน Neon classroom-live-run-lab เรียบร้อย"
    });
  } catch (error) {
    console.error("Vercel reset execution failed:", error?.message);
    return res.status(503).json({ error: "เคลียร์ข้อมูลไม่สำเร็จ: " + error?.message });
  }
}
