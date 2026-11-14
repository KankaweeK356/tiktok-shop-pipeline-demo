/** Report ML readiness only from the active completed Warehouse run. */
import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";
import { getNeonSql } from "./neon-router.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function labML(req, res) {
  res.setHeader("Cache-Control", "no-store");
  if (!["GET", "POST"].includes(req.method)) return res.status(405).json({ error: "GET/POST only" });
  const runId = String(req.method === "GET" ? req.query?.warehouse_run_id || "" : req.body?.warehouse_run_id || "");
  if (!UUID.test(runId)) return res.status(400).json({ error: "Warehouse Run ID ไม่ถูกต้อง" });
  try {
    const sql = getNeonSql("readonly");
    const rows = await sql.query(`SELECT r.status, d.phase
      FROM demo_control.dataset_state d
      JOIN demo_control.pipeline_runs r ON r.run_id=d.last_run_id
      WHERE d.dataset_key='classroom' AND r.run_id::text=$1
        AND r.cycle_number=d.cycle_number`, [runId]);
    if (!rows.length || rows[0].status !== "SUCCEEDED" || rows[0].phase === "EMPTY")
      return res.status(409).json({ ready: false, error: "ยังไม่มี Warehouse จาก Run ปัจจุบัน" });

    const storage = new S3Client({
      region: process.env.CLASSROOM_STORAGE_REGION || "auto",
      endpoint: process.env.CLASSROOM_STORAGE_ENDPOINT,
      forcePathStyle: true,
      credentials: { accessKeyId: process.env.CLASSROOM_STORAGE_KEY_ID,
        secretAccessKey: process.env.CLASSROOM_STORAGE_SECRET }
    });
    const object = await storage.send(new GetObjectCommand({
      Bucket: process.env.CLASSROOM_STORAGE_BUCKET,
      Key: `vercel-lab/results/${runId}/batch.json`
    }));
    const warehouse = JSON.parse(Buffer.from(await object.Body.transformToByteArray()).toString("utf8"));
    const readiness = warehouse.ml_readiness || {};
    const weeks = Number(readiness.complete_weeks || 0);
    const minimum = Number(readiness.minimum_weeks || 16);
    if (weeks < minimum) return res.status(req.method === "POST" ? 409 : 200).json({
      ready: false, status: "needs_more_data", warehouse_run_id: runId,
      complete_weeks: weeks, minimum_weeks: minimum,
      reason: readiness.reason || "ข้อมูล Warehouse รอบนี้ยังไม่พอสำหรับการฝึกและทดสอบตามลำดับเวลา"
    });
    return res.status(req.method === "POST" ? 503 : 200).json({
      ready: false, status: "training_unavailable", warehouse_run_id: runId,
      complete_weeks: weeks, minimum_weeks: minimum,
      error: "ระบบฝึกโมเดลจาก Warehouse รอบนี้ยังไม่พร้อม"
    });
  } catch (_error) {
    return res.status(503).json({ ready: false, error: "อ่านข้อมูล ML ของ Warehouse รอบปัจจุบันไม่ได้" });
  }
}
