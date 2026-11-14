/** Vercel Native Stage Result: Returns genuine stage evidence without calling GitHub Actions. */
import { buildStageEvidence } from "../lib/etl-engine.js";

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "GET") return res.status(405).json({ error: "GET only" });

  const id = String(req.query?.run_id || "");
  const stage = String(req.query?.stage || "ingest");
  const batch = String(req.query?.batch || (id.includes("incremental") ? "incremental_01" : "initial"));

  const evidence = buildStageEvidence(stage, batch);

  return res.status(200).json({
    run_id: id || `vercel_${stage}`,
    mode: "VERCEL_NATIVE_EXECUTION",
    receipt: evidence
  });
}
