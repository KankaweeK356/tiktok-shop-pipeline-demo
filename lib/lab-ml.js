/** Train ML only from the active, validated classroom Warehouse. */
import { neon } from "@neondatabase/serverless";
import { unzipSync, strFromU8 } from "fflate";

const REPO="KankaweeK356/tiktok-shop-pipeline-demo";
const REF="feature/classroom-demo-evidence-foundation";
const WORKFLOW="classroom-ml-train.yml";
const MINIMUM_WEEKS=16;
async function github(path,method="GET",body,raw=false){
  const response=await fetch("https://api.github.com/repos/"+REPO+path,{
    method,headers:{Authorization:"Bearer "+process.env.CLASSROOM_GITHUB_TOKEN,
      Accept:"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28",
      "User-Agent":"classroom-ml-lab"},
    ...(body?{body:JSON.stringify(body)}:{})});
  if(!response.ok)throw Error("GitHub HTTP "+response.status);
  return raw?new Uint8Array(await response.arrayBuffer()):
    response.status===204?null:response.json();
}
async function activeWarehouse(){
  const sql=neon(process.env.CLASSROOM_LAB_NEON_URL);
  const [rows,completed]=await Promise.all([sql.query(`SELECT d.phase,d.cycle_number,r.runner_ref,r.status
    FROM demo_control.dataset_state d LEFT JOIN demo_control.pipeline_runs r
    ON r.run_id=d.last_run_id WHERE d.dataset_key='classroom'`),
    sql.query(`SELECT COUNT(*)::int AS n FROM demo_control.pipeline_runs
      WHERE dataset_key='classroom' AND cycle_number=(SELECT cycle_number
      FROM demo_control.dataset_state WHERE dataset_key='classroom')
      AND status='SUCCEEDED' AND run_type IN ('RUN1','RUN2')`)]);
  const row=rows[0]||{};
  const id=String(row.runner_ref||"").match(/\/actions\/runs\/([1-9][0-9]*)\/?$/)?.[1];
  const workflow=id?await github("/actions/runs/"+id):null;
  const sourceV2=(workflow?.display_title||"").endsWith(" / source-v2");
  let readiness={complete_weeks:0,minimum_weeks:MINIMUM_WEEKS,ready:false};
  if(id&&["RUN1_READY","RUN2_READY"].includes(row.phase)&&row.status==="SUCCEEDED"){
    try{
      const listing=await github("/actions/runs/"+id+"/artifacts?per_page=30");
      const artifact=(listing.artifacts||[]).find(item=>item.name==="classroom-batch-result"&&!item.expired);
      if(artifact&&artifact.size_in_bytes<=5*1024*1024){
        const archive=unzipSync(await github("/actions/artifacts/"+artifact.id+"/zip","GET",null,true));
        const name=Object.keys(archive).find(item=>item==="batch_result.json"||item.endsWith("/batch_result.json"));
        if(name){const result=JSON.parse(strFromU8(archive[name]));
          readiness=result.ml_readiness||readiness;}
      }
    }catch(_error){/* Keep training locked until current Warehouse readiness is verifiable. */}
  }
  return {phase:row.phase,cycle:Number(row.cycle_number),runId:id||null,
    months:Number(completed[0]?.n||0),sourceV2,
    readiness,
    ready:["RUN1_READY","RUN2_READY"].includes(row.phase)&&row.status==="SUCCEEDED"&&sourceV2};
}
export default async function handler(req,res){
  res.setHeader("Cache-Control","no-store");
  if(!["GET","POST"].includes(req.method))return res.status(405).json({error:"GET/POST only"});
  if(!process.env.CLASSROOM_GITHUB_TOKEN||!process.env.CLASSROOM_LAB_NEON_URL)
    return res.status(503).json({error:"ML Lab ยังไม่พร้อม"});
  try{
    const active=await activeWarehouse();
    if(!active.ready)return res.status(200).json({ready:false,reason:active.sourceV2?
      "Warehouse ยังไม่มีข้อมูลที่ผ่านการตรวจ":"Lab ยังเป็น Source รุ่นเดิม กรุณาเคลียร์ Lab ก่อน"});
    if(!active.readiness.ready)return res.status(req.method==="POST"?409:200).json({
      ready:false,status:"needs_more_data",complete_weeks:active.readiness.complete_weeks,
      minimum_weeks:active.readiness.minimum_weeks,
      reason:"มีสัปดาห์ที่ครบและใช้ได้ "+active.readiness.complete_weeks+" จาก "+
        active.readiness.minimum_weeks+" สัปดาห์ · เติมข้อมูลรายเดือนถัดไปก่อนฝึกโมเดล"});
    const wanted=String(req.method==="POST"?req.body?.warehouse_run_id:req.query?.warehouse_run_id||"");
    if(wanted!==active.runId)return res.status(409).json({error:"Warehouse เปลี่ยนรอบแล้ว กรุณาโหลดหน้าใหม่"});
    const runs=await github("/actions/workflows/"+WORKFLOW+
      "/runs?branch="+encodeURIComponent(REF)+"&event=workflow_dispatch&per_page=30");
    const title="Classroom ML train / warehouse "+active.runId;
    const latest=(runs.workflow_runs||[]).find(run=>run.display_title===title);
    if(req.method==="POST"){
      if(latest&&latest.status!=="completed")
        return res.status(202).json({accepted:true,status:latest.status,run_id:latest.id});
      await github("/actions/workflows/"+WORKFLOW+"/dispatches","POST",{
        ref:REF,inputs:{warehouse_run_id:active.runId}});
      return res.status(202).json({accepted:true,status:"queued"});
    }
    if(!latest)return res.status(200).json({ready:true,status:"not_started"});
    if(latest.status!=="completed")return res.status(200).json({ready:true,
      status:latest.status,run_id:latest.id,url:latest.html_url});
    if(latest.conclusion!=="success")return res.status(200).json({ready:true,
      status:"failure",run_id:latest.id,url:latest.html_url});
    const listing=await github("/actions/runs/"+latest.id+"/artifacts?per_page=20");
    const artifact=(listing.artifacts||[]).find(x=>x.name==="classroom-ml-result"&&!x.expired);
    if(!artifact)return res.status(200).json({ready:true,status:"processing",run_id:latest.id});
    if(artifact.size_in_bytes>5*1024*1024)throw Error("ML result is too large");
    const files=unzipSync(await github("/actions/artifacts/"+artifact.id+"/zip","GET",null,true));
    const key=Object.keys(files).find(x=>x==="classroom_ml_result.json"||
      x.endsWith("/classroom_ml_result.json"));
    if(!key)throw Error("ML result artifact is incomplete");
    const result=JSON.parse(strFromU8(files[key]));
    if(result.classification!=="SYNTHETIC_EDUCATIONAL_NOT_TIKTOK"||
       Number(result.warehouse_cycle)!==active.cycle||
       result.source!=="CURRENT_CLASSROOM_WAREHOUSE")
      return res.status(409).json({error:"ผล ML ไม่ตรงกับ Warehouse ปัจจุบัน"});
    return res.status(200).json({ready:true,status:"success",run_id:latest.id,
      url:latest.html_url,result});
  }catch(error){
    console.error("Classroom ML request failed",error?.message);
    return res.status(503).json({error:"ติดต่อ ML Lab ไม่สำเร็จ"});
  }
}
