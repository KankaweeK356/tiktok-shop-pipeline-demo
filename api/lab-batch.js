/** Vercel entry point for the one-click monthly classroom pipeline. */
import { createHmac, randomUUID } from "node:crypto";
import { S3Client, HeadObjectCommand, GetObjectCommand } from "@aws-sdk/client-s3";
import { handleClassroomSourceUpload } from "../lib/classroom-source-upload.js";
import { getNeonSql } from "../lib/neon-router.js";
import { DELIVERIES, STAGES } from "../lib/etl-engine.js";

export const config = { api: { bodyParser: false } };
const RUN_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const storageReady = () => Boolean(process.env.CLASSROOM_STORAGE_BUCKET &&
  process.env.CLASSROOM_STORAGE_ENDPOINT && process.env.CLASSROOM_STORAGE_KEY_ID &&
  process.env.CLASSROOM_STORAGE_SECRET);
const ready = () => Boolean(process.env.CLASSROOM_LAB_WRITER_URL &&
  process.env.CLASSROOM_LAB_ADMIN_KEY && storageReady());

async function readJsonBody(req) {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of req) {
    bytes += chunk.length;
    if (bytes > 16384) throw Error("Request body too large");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}
function monthFor(batch) {
  const index = DELIVERIES.indexOf(batch);
  return index < 0 ? "" : `2026-${String(index + 1).padStart(2, "0")}`;
}
function expectedNext(phase, runs) {
  if (phase === "EMPTY") return "initial";
  const latest = runs[0];
  if (latest?.status === "FAILED" && latest.run_type === "RUN2") {
    const retry = latest.result_summary?.batch;
    if (retry && DELIVERIES.includes(retry) && retry !== "initial") return retry;
  }
  if (phase === "RUN1_READY") return "incremental_01";
  if (phase === "RUN2_READY") {
    const lastSuccess = runs.find(row => row.status === "SUCCEEDED");
    const lastBatch = lastSuccess?.result_summary?.batch ||
      (lastSuccess?.run_type === "RUN1" ? "initial" : "incremental_01");
    const index = DELIVERIES.indexOf(lastBatch);
    return index >= 0 ? (DELIVERIES[index + 1] || null) : null;
  }
  return null;
}
function executionUrl(req) {
  return "";
}
function clientForStorage() {
  return new S3Client({
    region: process.env.CLASSROOM_STORAGE_REGION || "auto",
    endpoint: process.env.CLASSROOM_STORAGE_ENDPOINT,
    forcePathStyle: true,
    credentials: {
      accessKeyId: process.env.CLASSROOM_STORAGE_KEY_ID,
      secretAccessKey: process.env.CLASSROOM_STORAGE_SECRET
    }
  });
}

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  if (req.method === "POST" &&
      String(req.headers["content-type"] || "").toLowerCase().includes("application/zip"))
    return handleClassroomSourceUpload(req, res);
  if ((req.method === "GET" && req.query?.id) || req.method === "DELETE")
    return handleClassroomSourceUpload(req, res);
  if (!["GET", "POST"].includes(req.method))
    return res.status(405).json({ error: "GET/POST only" });
  if (!ready())
    return res.status(503).json({ ready: false, error: "Vercel Lab หรือพื้นที่จัดเก็บงานยังตั้งค่าไม่ครบ" });

  let sql;
  try { sql = getNeonSql("live"); }
  catch (_error) { return res.status(503).json({ ready: false, error: "เชื่อมต่อ Neon Lab ไม่ได้" }); }

  let state, runs, orderRows;
  try {
    [state, runs, orderRows] = await Promise.all([
      sql.query("SELECT phase,cycle_number,last_run_id FROM demo_control.dataset_state WHERE dataset_key='classroom' LIMIT 1"),
      sql.query("SELECT run_id::text,run_type,status,started_at,result_summary,error_message,cycle_number FROM demo_control.pipeline_runs WHERE dataset_key='classroom' AND cycle_number=(SELECT cycle_number FROM demo_control.dataset_state WHERE dataset_key='classroom') ORDER BY started_at DESC LIMIT 30"),
      sql.query('SELECT COUNT(*)::int AS n FROM demo_er1."Fact_Orders"')
    ]);
  } catch (_error) {
    return res.status(503).json({ ready: false, error: "อ่านสถานะจริงจาก Neon Lab ไม่ได้" });
  }
  const lab = state[0];
  if (!lab) return res.status(503).json({ ready: false, error: "ไม่พบสถานะรอบทดลองใน Neon" });
  const phase = lab.phase || "EMPTY";
  const cycle = Number(lab.cycle_number);
  const previousRunId = lab.last_run_id ? String(lab.last_run_id) : "0";
  const active = runs.find(row => ["RUNNING", "QUEUED"].includes(row.status));
  const next = expectedNext(phase, runs);
  const currentRuns = runs.slice().reverse().map(row => {
    const batch = row.result_summary?.batch ||
      (row.run_type === "RUN1" ? "initial" : "incremental_01");
    return {
      run_id: String(row.run_id), batch: batch === "initial" ? "initial" : "incremental",
      source_batch: batch, source_month: monthFor(batch), status: row.status,
      created_at: row.started_at, execution_engine: "VERCEL_NATIVE"
    };
  });

  if (req.method === "GET") {
    const batchQuery = String(req.query?.batch || "");
    if (batchQuery) {
      const since = Date.parse(String(req.query?.since || ""));
      if (!Number.isFinite(since) || !["initial", "incremental"].includes(batchQuery))
        return res.status(400).json({ error: "ข้อมูลติดตาม Run ไม่ถูกต้อง" });
      const type = batchQuery === "initial" ? "RUN1" : "RUN2";
      const requestedId = String(req.query?.run_id || "");
      if (requestedId && !RUN_UUID.test(requestedId)) return res.status(400).json({ error: "Run ID ไม่ถูกต้อง" });
      const run = runs.find(row => row.run_type === type && (requestedId ?
        String(row.run_id) === requestedId : Date.parse(row.started_at) >= since - 15000));
      if (!run) return res.status(200).json({ found: false, status: "queued", stages: [] });
      let stageRows = [];
      try {
        stageRows = await sql.query(
          "SELECT stage_name,status,finished_at,metrics FROM demo_control.stage_runs WHERE run_id=$1",
          [run.run_id]);
      } catch (_error) {
        return res.status(503).json({ error: "อ่านสถานะขั้นตอนจาก Neon ไม่ได้" });
      }
      const failedStage = run.result_summary?.failed_stage;
      let failureEvidence = null;
      if (run.status === "FAILED") {
        try {
          const object = await clientForStorage().send(new GetObjectCommand({
            Bucket: process.env.CLASSROOM_STORAGE_BUCKET,
            Key: `vercel-lab/failed/${run.run_id}.json`
          }));
          failureEvidence = JSON.parse(Buffer.from(await object.Body.transformToByteArray()).toString("utf8"));
        } catch (_error) { /* Neon remains the authoritative failure record. */ }
      }
      const stages = STAGES.map((name, index) => {
        const saved = stageRows.find(row => row.stage_name === name);
        const pendingAfterFailure = run.status === "FAILED" && failedStage &&
          STAGES.indexOf(name) > STAGES.indexOf(failedStage);
        return {
          index, name,
          status: saved?.status === "SUCCESS" ? "completed" :
            saved?.status === "FAILED" ? "completed" :
              pendingAfterFailure ? "pending" : saved?.status === "RUNNING" ? "in_progress" : "pending",
          conclusion: saved?.status === "SUCCESS" ? "success" :
            saved?.status === "FAILED" ? "failure" : null,
          completed_at: saved?.finished_at || null
        };
      });
      const done = ["SUCCEEDED", "FAILED"].includes(run.status);
      return res.status(200).json({
        found: true, run_id: String(run.run_id), stages,
        status: done ? "completed" : "in_progress",
        conclusion: run.status === "SUCCEEDED" ? "success" : run.status === "FAILED" ? "failure" : null,
        failed_stage: failureEvidence?.failed_stage || failedStage || null,
        error_code: failureEvidence?.error_code || run.result_summary?.error_code || run.error_message || null,
        error_message: failureEvidence?.message || run.error_message || null,
        source_batch: run.result_summary?.batch || null,
        url: executionUrl(req), execution_engine: "VERCEL_NATIVE"
      });
    }
    return res.status(200).json({
      ready: true, phase, cycle, orders: orderRows[0]?.n ?? 0,
      current_run_id: previousRunId === "0" ? null : previousRunId,
      current_run_type: phase === "RUN1_READY" ? "RUN1" : phase === "RUN2_READY" ? "RUN2" : null,
      requires_reset: false, running: Boolean(active),
      active_run_type: active?.run_type || null,
      active_run_id: active ? String(active.run_id) : null,
      active_stage: active?.result_summary?.active_stage || null,
      previous_run_id: previousRunId, next_source_batch: next,
      source_remaining: next ? DELIVERIES.length - DELIVERIES.indexOf(next) : 0,
      source_exhausted: !next, history: currentRuns.slice().reverse(),
      current_cycle_runs: currentRuns, execution_engine: "VERCEL_NATIVE"
    });
  }

  let body;
  try { body = await readJsonBody(req); }
  catch (_error) { return res.status(400).json({ error: "ข้อมูลคำขอ Run ไม่ถูกต้อง" }); }
  if (active) return res.status(409).json({ error: "มี Run กำลังทำงานอยู่ กรุณารอให้จบก่อน" });
  const requested = String(body.batch || "");
  const requestedBatch = requested === "initial" ? "initial" :
    requested === "incremental" ? next : requested;
  const previous = String(body.previous_run_id || "0");
  if (!requestedBatch || !DELIVERIES.includes(requestedBatch) || requestedBatch !== next)
    return res.status(409).json({ error: "Source เดือนถัดไปไม่ตรงกับสถานะปัจจุบันใน Neon" });
  if ((requestedBatch === "initial" && (phase !== "EMPTY" || previous !== "0")) ||
      (requestedBatch !== "initial" &&
       (phase !== "RUN1_READY" && phase !== "RUN2_READY" || previous !== previousRunId || !RUN_UUID.test(previous))))
    return res.status(409).json({ error: "Run ก่อนหน้าหรือสถานะ Lab ไม่ตรงกับรอบข้อมูล" });

  const sourceUploadId = String(body.source_upload_id || "");
  if (sourceUploadId) {
    if (!/^[0-9a-f-]{36}$/i.test(sourceUploadId))
      return res.status(400).json({ error: "รหัสไฟล์ Source ไม่ถูกต้อง" });
    try {
      const item = await clientForStorage().send(new HeadObjectCommand({
        Bucket: process.env.CLASSROOM_STORAGE_BUCKET,
        Key: `classroom-source-uploads/${sourceUploadId}.zip`
      }));
      if (item.Metadata?.month !== monthFor(requestedBatch))
        return res.status(409).json({ error: "ไฟล์ Source ต้องเป็นเดือน " + monthFor(requestedBatch) });
    } catch (_error) {
      return res.status(404).json({ error: "ไม่พบไฟล์ Source ที่อัปโหลด หรือไฟล์หมดอายุแล้ว" });
    }
  }

  const claim = {
    batch: requestedBatch, previous_run_id: previous, cycle,
    source_upload_id: sourceUploadId || null, nonce: randomUUID(),
    expires_at: Date.now() + 10 * 60 * 1000
  };
  const encoded = Buffer.from(JSON.stringify(claim)).toString("base64url");
  const signature = createHmac("sha256", process.env.CLASSROOM_LAB_ADMIN_KEY)
    .update(encoded).digest("hex");
  return res.status(202).json({
    accepted: true, execution: "VERCEL_NATIVE", ticket: encoded + "." + signature,
    run_id: claim.nonce, source_batch: requestedBatch, source_month: monthFor(requestedBatch),
    status: "queued", workflow_url: executionUrl(req)
  });
}
