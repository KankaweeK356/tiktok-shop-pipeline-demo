/** Live read-only Neon run status. Does not expose source digests, credentials or tokens. */
import { neon } from "@neondatabase/serverless";

export default async function handler(req,res){
  res.setHeader("Cache-Control","private, no-store");
  res.setHeader("X-Content-Type-Options","nosniff");
  if(req.method!=="GET"){res.setHeader("Allow","GET");return res.status(405).json({error:"GET only"});}
  const connection=process.env.CLASSROOM_NEON_READONLY_URL;
  if(!connection)return res.status(503).json({connected:false,error:"ยังไม่ได้ตั้งค่าการเชื่อมต่อ Neon"});
  try{
    const sql=neon(connection);
    const [state,runs,counts]=await Promise.all([
      sql.query("SELECT phase,cycle_number,lock_version,updated_at,last_run_id FROM demo_control.dataset_state WHERE dataset_key='classroom' LIMIT 1"),
      sql.query(`SELECT run_id::text,run_type,status,runner_ref,triggered_by,created_at,
                result_summary->>'backfill_type' AS evidence_type,
                result_summary->>'note' AS evidence_note
                FROM demo_control.pipeline_runs WHERE dataset_key='classroom'
                ORDER BY created_at DESC LIMIT 12`),
      sql.query(`SELECT (SELECT COUNT(*) FROM demo_er1."Fact_Orders")::int AS orders,
                (SELECT COUNT(*) FROM demo_er1."Fact_Order_Items")::int AS order_items,
                (SELECT COUNT(*) FROM demo_control.pipeline_artifacts)::int AS artifacts,
                (SELECT COUNT(*) FROM demo_control.stage_runs)::int AS stage_records`),
    ]);
    return res.status(200).json({connected:true,origin:"NEON_LIVE",branch:"demo-pipeline",
      state:state[0]??null,runs,counts:counts[0],generated_at:new Date().toISOString(),
      artifact_scope:"metadata recorded in Neon; does not prove object bytes exist without verification"});
  }catch(err){
    console.error("Neon run status error",err?.code||err?.name||"unknown");
    return res.status(503).json({connected:false,error:"ไม่สามารถตรวจสอบสถานะ Pipeline จาก Neon ได้"});
  }
}
