/** Return persisted evidence for a real Vercel-run batch only. */
import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";
import labML from "../lib/lab-ml.js";
import { getNeonSql } from "../lib/neon-router.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const STAGES = new Set(["ingest", "extract", "transform", "load", "validate"]);
function storage() {
  return new S3Client({
    region: process.env.CLASSROOM_STORAGE_REGION || "auto",
    endpoint: process.env.CLASSROOM_STORAGE_ENDPOINT,
    forcePathStyle: true,
    credentials: { accessKeyId: process.env.CLASSROOM_STORAGE_KEY_ID,
      secretAccessKey: process.env.CLASSROOM_STORAGE_SECRET }
  });
}
async function readObject(key) {
  const response = await storage().send(new GetObjectCommand({
    Bucket: process.env.CLASSROOM_STORAGE_BUCKET, Key: key
  }));
  return response.Body.transformToByteArray();
}
function notFound(error) {
  return error?.$metadata?.httpStatusCode === 404 || error?.name === "NoSuchKey";
}

export default async function handler(req, res) {
  if (req.query?.ml === "1") return labML(req, res);
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "GET") return res.status(405).json({ error: "GET only" });
  if (req.query?.download === "warehouse") {
    const id = String(req.query?.run_id || "");
    if (!UUID.test(id)) return res.status(400).json({ error: "ต้องระบุ Run ID ที่ถูกต้อง" });
    try {
      const bytes = await readObject(`vercel-lab/results/${id}/warehouse.zip`);
      res.setHeader("Content-Type", "application/zip");
      res.setHeader("Content-Disposition", `attachment; filename="warehouse-${id}.zip"`);
      return res.status(200).send(Buffer.from(bytes));
    } catch (error) {
      return res.status(notFound(error) ? 404 : 503).json({
        error: notFound(error) ? "Run นี้ยังไม่มีไฟล์ Warehouse ที่สร้างจากข้อมูลจริง" : "อ่านไฟล์ Warehouse ไม่สำเร็จ"
      });
    }
  }

  const id = String(req.query?.run_id || "");
  const stage = String(req.query?.stage || "");
  if (!UUID.test(id)) return res.status(400).json({ error: "Run ID ไม่ถูกต้อง" });
  if (stage && !STAGES.has(stage)) return res.status(400).json({ error: "Step ไม่ถูกต้อง" });
  try {
    const sql = getNeonSql("live");
    const rows = await sql.query(
      "SELECT status,result_summary,error_message FROM demo_control.pipeline_runs WHERE run_id::text=$1 LIMIT 1", [id]);
    if (!rows.length) return res.status(404).json({ error: "ไม่พบ Run นี้ใน Neon Lab" });
    const run = rows[0];
    if (run.status === "FAILED") {
      let failure = { status: "FAILED", run_id: id, message: "Pipeline หยุดก่อนจบ" };
      try { failure = JSON.parse(Buffer.from(await readObject(`vercel-lab/failed/${id}.json`)).toString("utf8")); }
      catch (_error) { /* Keep the authoritative Neon failure status. */ }
      return res.status(200).json({ run_id: id, result: failure });
    }
    if (run.status !== "SUCCEEDED") return res.status(409).json({ error: "Run นี้ยังทำงานไม่เสร็จ" });
    const key = `vercel-lab/results/${id}/${stage ? `${stage}.json` : "batch.json"}`;
    const evidence = JSON.parse(Buffer.from(await readObject(key)).toString("utf8"));
    return res.status(200).json(stage ? { run_id: id, stage, evidence } : {
      run_id: id, result: evidence, execution: "VERCEL_NATIVE"
    });
  } catch (error) {
    return res.status(notFound(error) ? 404 : 503).json({
      error: notFound(error) ? "ไม่พบหลักฐานที่บันทึกไว้สำหรับ Run นี้" : "อ่านผลจริงจาก Neon หรือพื้นที่จัดเก็บไม่สำเร็จ"
    });
  }
}
