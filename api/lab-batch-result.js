/**
 * Return persisted evidence and results for Vercel ETL executions.
 */
import { S3Client, GetObjectCommand } from "@aws-sdk/client-s3";
import labML from "../lib/lab-ml-live.js";
import { getNeonSql } from "../lib/neon-router.js";
import { getPublishedBusinessData, getPipelineStatus } from "../lib/etl-engine.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const STAGES = new Set(["ingest", "extract", "transform", "load", "validate"]);

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("X-Content-Type-Options", "nosniff");

  if (req.method !== "GET") {
    return res.status(405).json({ error: "GET only" });
  }

  // Business decision dashboard data
  if (req.query?.business === "1") {
    const data = getPublishedBusinessData();
    return res.status(200).json(data);
  }

  // ML Lab data
  if (req.query?.ml === "1") {
    return labML(req, res);
  }

  // Pipeline status
  if (req.query?.status === "1") {
    const status = getPipelineStatus();
    return res.status(200).json(status);
  }

  const id = String(req.query?.run_id || "");
  const stage = String(req.query?.stage || "");

  // If no run_id supplied, return latest pipeline status
  if (!id) {
    const status = getPipelineStatus();
    return res.status(200).json(status);
  }

  if (stage && !STAGES.has(stage)) {
    return res.status(400).json({ error: "Step ไม่ถูกต้อง" });
  }

  // Read from Neon or in-memory state
  try {
    let sql = null;
    try { sql = getNeonSql("live"); } catch (_e) { }

    if (sql) {
      const rows = await sql.query(
        "SELECT status, result_summary, error_message FROM demo_control.pipeline_runs WHERE run_id::text=$1 LIMIT 1",
        [id]
      );
      if (rows.length) {
        const run = rows[0];
        return res.status(200).json({ run_id: id, status: run.status, result: run.result_summary });
      }
    }

    const currentStatus = getPipelineStatus();
    return res.status(200).json({ run_id: id, result: currentStatus });
  } catch (error) {
    return res.status(500).json({ error: "อ่านผลลัพธ์ไม่สำเร็จ: " + error.message });
  }
}
