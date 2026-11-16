/**
 * Vercel Serverless API entry point for Single Main-Flow Pipeline Runner.
 * Supports:
 * - GET: Status of 10 months, active batch, next eligible stage, and stage receipts
 * - POST:
 *     - action: "run_next" -> executes exactly ONE stage for current batch
 *     - action: "execute_stage" -> executes requested (batch, stage)
 *     - action: "submit_fix" -> records human Data Owner fix for quarantined SKU
 *     - action: "reset" -> resets demo to initial state
 */
import { 
  getPipelineStatus, 
  executeSingleStage, 
  submitCorrection, 
  resetDemoState, 
  DELIVERIES, 
  STAGES, 
  MONTH_NAMES, 
  monthForBatch 
} from "../lib/etl-engine.js";

// Concurrency lock for serverless execution
let lockToken = null;
let lockExpiresAt = 0;

function acquireLock() {
  const now = Date.now();
  if (lockToken && now < lockExpiresAt) {
    return false; // Currently locked
  }
  lockToken = Math.random().toString(36).slice(2);
  lockExpiresAt = now + 15000; // 15-second lease
  return true;
}

function releaseLock() {
  lockToken = null;
  lockExpiresAt = 0;
}

async function readJsonBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  const chunks = [];
  let bytes = 0;
  for await (const chunk of req) {
    bytes += chunk.length;
    if (bytes > 65536) throw new Error("Request body too large");
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("X-Content-Type-Options", "nosniff");

  if (!["GET", "POST"].includes(req.method)) {
    return res.status(405).json({ error: "GET/POST only" });
  }

  // --- GET: Query Pipeline Status & Stage Evidence ---
  if (req.method === "GET") {
    try {
      const status = getPipelineStatus();
      return res.status(200).json(status);
    } catch (err) {
      console.error("GET /api/lab-batch error:", err);
      return res.status(500).json({ error: err.message || "เกิดข้อผิดพลาดในการอ่านสถานะ" });
    }
  }

  // --- POST: Actions ---
  let body = {};
  try {
    body = await readJsonBody(req);
  } catch (err) {
    return res.status(400).json({ error: "รูปแบบข้อมูล JSON ไม่ถูกต้อง" });
  }

  const action = body.action || "run_next";

  // Action: Reset Demo
  if (action === "reset") {
    releaseLock();
    const result = resetDemoState();
    return res.status(200).json(result);
  }

  // Action: Submit Human Correction (March error recovery)
  if (action === "submit_fix") {
    try {
      const result = submitCorrection({
        order_item_id: body.order_item_id,
        corrected_sku: body.corrected_sku,
        actor: body.actor,
        reason: body.reason
      });
      return res.status(200).json(result);
    } catch (err) {
      return res.status(400).json({ error: err.message });
    }
  }

  // Action: Execute Next Stage or Specific Stage
  if (!acquireLock()) {
    return res.status(409).json({ 
      error: "ระบบกำลังประมวลผลขั้นตอนก่อนหน้าอยู่ กรุณารอสักครู่ (Concurrency Guard)",
      status: "LOCKED"
    });
  }

  try {
    const currentStatus = getPipelineStatus();

    if (currentStatus.is_blocked) {
      releaseLock();
      return res.status(400).json({
        error: "พบข้อมูลไม่ผ่านการตรวจสอบ — หยุดการประมวลผลเพื่อแก้ไข",
        status: "BLOCKED",
        quarantine: currentStatus.quarantine
      });
    }

    if (currentStatus.is_completed) {
      releaseLock();
      return res.status(200).json({
        message: "ประมวลผลครบทั้ง 10 เดือนเรียบร้อยแล้ว",
        is_completed: true
      });
    }

    let targetBatch = body.batch || currentStatus.active_batch;
    let targetStage = body.stage || currentStatus.next_stage;

    if (!targetBatch || !DELIVERIES.includes(targetBatch)) {
      targetBatch = currentStatus.active_batch;
    }
    if (!targetStage || !STAGES.includes(targetStage)) {
      targetStage = currentStatus.next_stage || "ingest";
    }

    // Execute single stage
    const stageReceipt = await executeSingleStage(targetBatch, targetStage, {
      overridePatch: body.overridePatch || null
    });

    const updatedStatus = getPipelineStatus();

    releaseLock();

    return res.status(200).json({
      success: stageReceipt.success,
      batch: targetBatch,
      stage: targetStage,
      month: monthForBatch(targetBatch),
      receipt: stageReceipt,
      pipeline_status: updatedStatus,
      is_blocked: updatedStatus.is_blocked,
      is_completed: updatedStatus.is_completed
    });

  } catch (err) {
    releaseLock();
    console.error("ETL Stage execution error:", err);
    return res.status(500).json({ 
      error: err.message || "เกิดข้อผิดพลาดในการประมวลผลขั้นตอน",
      stack: process.env.NODE_ENV === "development" ? err.stack : undefined
    });
  }
}
