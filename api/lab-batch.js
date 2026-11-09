/** Vercel orchestration for one complete real classroom batch. */
import { neon } from "@neondatabase/serverless";

const STAGES=["ingest","extract","transform","load","validate"];
const phaseFor=batch=>batch==="initial"?"EMPTY":"RUN1_READY";
const typeFor=batch=>batch==="initial"?"RUN1":"RUN2";
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export default async function handler(req,res){
  res.setHeader("Cache-Control","no-store");
  if(!["GET","POST"].includes(req.method))return res.status(405).json({error:"GET/POST only"});
  if(!process.env.CLASSROOM_LAB_NEON_URL||!process.env.CLASSROOM_LAB_WRITER_URL||
     !process.env.CLASSROOM_LAB_ADMIN_KEY||!process.env.CLASSROOM_STORAGE_BUCKET)
    return res.status(503).json({error:"Lab ยังไม่พร้อม"});
  try{
    const sql=neon(process.env.CLASSROOM_LAB_NEON_URL);
    const [state]=await sql.query("SELECT phase,cycle_number FROM demo_control.dataset_state WHERE dataset_key='classroom'");
    if(!state)return res.status(503).json({error:"อ่านสถานะ Lab ไม่ได้"});
    if(req.method==="GET"){
      if(req.query?.health==="1"){
        const worker=await fetch("https://"+req.headers.host+"/api/lab-worker",{
          method:"POST",headers:{"Content-Type":"application/json",
            "X-Classroom-Worker-Key":process.env.CLASSROOM_LAB_ADMIN_KEY},
          body:JSON.stringify({check:true})});
        return res.status(worker.status).json(await worker.json());
      }
      const batch=String(req.query?.batch||"");
      const all=await sql.query(
        "SELECT run_id::text,run_type,status,started_at FROM demo_control.pipeline_runs "+
        "WHERE dataset_key='classroom' AND cycle_number=$1 AND run_type IN ('RUN1','RUN2') "+
        "ORDER BY started_at DESC LIMIT 10",[state.cycle_number]);
      if(!batch){
        const initial=all.find(x=>x.run_type==="RUN1"&&x.status==="SUCCEEDED");
        const active=all.find(x=>x.status==="RUNNING");
        return res.status(200).json({ready:true,phase:state.phase,cycle:state.cycle_number,
          previous_run_id:initial?.run_id||null,
          resume_batch:active?.run_type==="RUN1"?"initial":active?.run_type==="RUN2"?"incremental":null,
          resume_run_id:active?.run_id||null,
          history:all.filter(x=>x.status==="SUCCEEDED").map(x=>({
            run_id:x.run_id,batch:x.run_type==="RUN1"?"initial":"incremental",
            created_at:x.started_at})),
          workflow_url:"https://"+req.headers.host+"/test-pipeline"});
      }
      const since=Date.parse(String(req.query?.since||""));
      if(!["initial","incremental"].includes(batch)||!Number.isFinite(since))
        return res.status(400).json({error:"ข้อมูลติดตามไม่ถูกต้อง"});
      const run=all.find(x=>x.run_type===typeFor(batch)&&
        Date.parse(x.started_at)>=since-10000);
      if(!run)return res.status(200).json({found:false,status:"queued",stages:[]});
      const rows=await sql.query(
        "SELECT stage_name,status,finished_at FROM demo_control.stage_runs WHERE run_id=$1",
        [run.run_id]);
      const stages=STAGES.map((stage,index)=>{
        const item=rows.find(x=>x.stage_name===stage);
        return {index,status:item?"completed":run.status==="RUNNING"?"in_progress":"completed",
          conclusion:item?.status==="SUCCESS"?"success":item?.status==="FAILED"?"failure":null,
          completed_at:item?.finished_at||null};
      });
      return res.status(200).json({found:true,run_id:run.run_id,stages,
        status:run.status==="RUNNING"?"in_progress":"completed",
        conclusion:run.status==="SUCCEEDED"?"success":"failure",
        url:"https://"+req.headers.host+"/test-pipeline"});
    }
    const batch=String(req.body?.batch||"");
    const previous=String(req.body?.previous_run_id||"");
    if(!["initial","incremental"].includes(batch)||state.phase!==phaseFor(batch))
      return res.status(409).json({error:"Lab ยังไม่พร้อมสำหรับ Run นี้"});
    const prior=await sql.query(
      "SELECT run_id::text FROM demo_control.pipeline_runs WHERE dataset_key='classroom' "+
      "AND cycle_number=$1 AND run_type='RUN1' AND status='SUCCEEDED' "+
      "ORDER BY started_at DESC LIMIT 1",[state.cycle_number]);
    if((batch==="initial"&&previous!=="0")||
       (batch==="incremental"&&(!uuid.test(previous)||previous!==prior[0]?.run_id)))
      return res.status(409).json({error:"Run ก่อนหน้าไม่ตรงกับรอบข้อมูล"});
    const target="https://"+req.headers.host+"/api/lab-worker";
    const worker=await fetch(target,{method:"POST",headers:{
      "Content-Type":"application/json",
      "X-Classroom-Worker-Key":process.env.CLASSROOM_LAB_ADMIN_KEY},
      body:JSON.stringify({batch,previous_run_id:previous})});
    const result=await worker.json();
    if(!worker.ok)return res.status(worker.status).json({error:result.error||"Vercel ETL ไม่สำเร็จ"});
    return res.status(202).json({accepted:true,run_id:result.run_id,
      workflow_url:"https://"+req.headers.host+"/test-pipeline"});
  }catch(error){
    console.error("Vercel classroom run failed",error?.name);
    return res.status(503).json({error:"รัน ETL บน Vercel ไม่สำเร็จ"});
  }
}
