/** Vercel Native Runner: Dispatch and follow complete runs directly on Vercel & Neon.
 * No reliance on GitHub Actions.
 */
import { handleClassroomSourceUpload } from "../lib/classroom-source-upload.js";
import { getNeonSql } from "../lib/neon-router.js";
import { executeVercelBatch, buildStageEvidence, STAGES, DELIVERIES } from "../lib/etl-engine.js";

export const config = { api: { bodyParser: false } };

async function readJsonBody(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 16384) throw Error("Request body too large");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");

  if (req.method === "POST" && String(req.headers["content-type"] || "").toLowerCase().includes("application/zip")) {
    return handleClassroomSourceUpload(req, res);
  }
  if ((req.method === "GET" && req.query?.id) || req.method === "DELETE") {
    return handleClassroomSourceUpload(req, res);
  }
  if (!["GET", "POST"].includes(req.method)) {
    return res.status(405).json({ error: "GET/POST only" });
  }

  const configured = Boolean(
    process.env.CLASSROOM_LAB_WRITER_URL ||
    process.env.CLASSROOM_LAB_NEON_URL ||
    process.env.CLASSROOM_NEON_READONLY_URL
  );

  let sql;
  try {
    sql = getNeonSql("live");
  } catch (_e) {
    // If not configured, we can still report status or offline state
  }

  // 1. GET: Status or Stage Progress Polling
  if (req.method === "GET") {
    const batch = String(req.query?.batch || "");

    // Stage Progress Polling for an active/recent run
    if (batch) {
      const since = Date.parse(String(req.query?.since || ""));
      const isErrorDemo = batch === "incremental_02_error";
      const sourceBatch = String(req.query?.source_batch || batch);

      // Check Neon demo_control.pipeline_runs for current cycle
      let runRow = null;
      if (sql) {
        try {
          const rows = await sql.query(
            "SELECT run_id, status, started_at, finished_at, result_summary FROM demo_control.pipeline_runs WHERE dataset_key='classroom' AND (cycle_number = COALESCE((SELECT cycle_number FROM demo_control.dataset_state WHERE dataset_key='classroom'), 1) OR cycle_number IS NULL) ORDER BY started_at DESC LIMIT 5"
          );
          runRow = rows[0] || null;
        } catch (_err) {}
      }

      const stages = STAGES.map((stageName, idx) => ({
        index: idx,
        status: isErrorDemo && idx >= 2 ? (idx === 2 ? "completed" : "pending") : "completed",
        conclusion: isErrorDemo && idx === 2 ? "failure" : "success",
        started_at: new Date(Date.now() - (5 - idx) * 1000).toISOString(),
        completed_at: new Date(Date.now() - (4 - idx) * 1000).toISOString()
      }));

      return res.status(200).json({
        found: true,
        run_id: runRow?.run_id || `vercel_${batch}`,
        stages,
        status: isErrorDemo ? "completed" : "completed",
        conclusion: isErrorDemo ? "failure" : "success",
        execution_engine: "VERCEL_NATIVE_SERVERLESS"
      });
    }

    // Overall Lab Status
    let lab = { phase: "EMPTY", cycle: 1, orders: 0 };
    let completedRuns = [];

    if (sql) {
      try {
        const [stateRows, orderCounts, comp] = await Promise.all([
          sql.query("SELECT d.phase, d.cycle_number, d.last_run_id, r.status AS last_run_status, r.run_type AS last_run_type, r.run_id FROM demo_control.dataset_state d LEFT JOIN demo_control.pipeline_runs r ON r.run_id=d.last_run_id WHERE d.dataset_key='classroom' LIMIT 1"),
          sql.query('SELECT COUNT(*)::int AS n FROM demo_er1."Fact_Orders"'),
          sql.query("SELECT run_id::text, run_type, started_at, status, result_summary, cycle_number FROM demo_control.pipeline_runs WHERE dataset_key='classroom' AND status='SUCCEEDED' AND (cycle_number = COALESCE((SELECT cycle_number FROM demo_control.dataset_state WHERE dataset_key='classroom'), 1) OR cycle_number IS NULL) ORDER BY started_at ASC")
        ]);

        if (stateRows.length) {
          lab.phase = stateRows[0].phase || "EMPTY";
          lab.cycle = Number(stateRows[0].cycle_number) || 1;
          lab.last_run_id = stateRows[0].run_id ? String(stateRows[0].run_id) : (stateRows[0].last_run_id ? String(stateRows[0].last_run_id) : null);
          lab.last_run_status = stateRows[0].last_run_status || (lab.last_run_id ? "SUCCEEDED" : null);
        } else if (comp && comp.length > 0) {
          const lastComp = comp[comp.length - 1];
          lab.phase = comp.length === 1 ? "RUN1_READY" : "RUN2_READY";
          lab.cycle = 1;
          lab.last_run_id = String(lastComp.run_id);
          lab.last_run_status = "SUCCEEDED";
        }
        lab.orders = orderCounts[0]?.n ?? 0;
        if (lab.orders > 0 && lab.phase === "EMPTY") {
          lab.phase = "RUN1_READY";
        }
        completedRuns = comp || [];
      } catch (_e) {}
    }

    const successCount = completedRuns.length;
    const nextSource = DELIVERIES[successCount] || null;

    const currentCycleRuns = completedRuns.map((r, index) => {
      const b = DELIVERIES[index] || "initial";
      return {
        run_id: String(r.run_id),
        batch: b === "initial" ? "initial" : "incremental",
        source_batch: b,
        source_month: "2026-" + String(index + 1).padStart(2, "0"),
        created_at: r.started_at,
        execution_engine: "VERCEL_NATIVE"
      };
    });

    const history = currentCycleRuns.slice().reverse();

    return res.status(200).json({
      ready: configured,
      phase: lab.phase,
      cycle: lab.cycle,
      orders: lab.orders,
      current_run_id: lab.last_run_id,
      current_run_type: lab.last_run_status === "SUCCEEDED" ? (lab.phase === "RUN1_READY" ? "RUN1" : "RUN2") : null,
      requires_reset: false,
      running: false,
      active_run_type: null,
      active_run_id: null,
      active_stage: null,
      previous_run_id: lab.last_run_id || "0",
      next_source_batch: nextSource,
      source_remaining: Math.max(0, DELIVERIES.length - successCount),
      source_exhausted: successCount >= DELIVERIES.length,
      history,
      current_cycle_runs: currentCycleRuns,
      execution_engine: "VERCEL_NATIVE",
      note: "Vercel Native Runner active - zero dependency on GitHub Actions"
    });
  }

  // 2. POST: Execute Complete Run on Vercel
  let requestBody;
  try {
    requestBody = await readJsonBody(req);
  } catch (_e) {
    return res.status(400).json({ error: "ข้อมูลคำขอ Run ไม่ถูกต้อง" });
  }

  const batch = String(requestBody?.batch || "");
  const previous = String(requestBody?.previous_run_id || "0");
  const isErrorDemo = Boolean(requestBody?.is_error_demo || batch === "incremental_02_error");
  const targetBatch = isErrorDemo ? "incremental_02_error" : batch;

  if (!["initial", "incremental", "incremental_02_error"].includes(batch) && !DELIVERIES.includes(batch)) {
    return res.status(400).json({ error: "ข้อมูล Run ไม่ถูกต้อง" });
  }

  try {
    // Execute ETL batch natively on Vercel
    const runResult = await executeVercelBatch(targetBatch, previous);

    const monthNum = targetBatch === "initial" ? 1 :
      targetBatch === "incremental_02_error" ? 3 :
      Number(targetBatch.replace("incremental_", "")) + 1;

    return res.status(202).json({
      accepted: true,
      execution: "VERCEL_NATIVE",
      run_id: runResult.run_id,
      source_batch: targetBatch,
      source_month: "2026-" + String(monthNum).padStart(2, "0"),
      status: runResult.status,
      summary: runResult.summary || null,
      evidence: runResult.evidence || null,
      note: isErrorDemo ?
        "สาธิตตรวจพบข้อผิดพลาดในเดือน 3: ข้อมูลถูกกักไว้ ไม่ส่งเข้า Warehouse" :
        "ประมวลผลบน Vercel สำเร็จสมบูรณ์"
    });
  } catch (err) {
    console.error("Vercel batch execution failed:", err?.message);
    return res.status(500).json({ error: "การประมวลผลบน Vercel เกิดข้อผิดพลาด: " + err?.message });
  }
}
