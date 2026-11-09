/** Dispatch one genuine GitHub Actions pipeline stage. No anonymous writes.
 * The Preview remains READ-ONLY until BOTH server-side secrets are configured:
 * CLASSROOM_GITHUB_TOKEN (fine-grained Actions RW scoped to this repo),
 * CLASSROOM_LAB_ADMIN_KEY (private operator key, not a GitHub credential).
 *
 * NEVER use this endpoint to reset Neon, and never pass credentials as workflow inputs.
 */
import { timingSafeEqual } from "node:crypto";
import { neon } from "@neondatabase/serverless";

const REPO="KankaweeK356/tiktok-shop-pipeline-demo";
const REF="feature/classroom-demo-evidence-foundation";
const WORKFLOW="classroom-real-step.yml";
const STAGES=["ingest","extract","transform","load","validate"];
const json=(res,code,value)=>res.status(code).json(value);
const safeEquals=(a,b)=>{
  const x=Buffer.from(a||""),y=Buffer.from(b||"");
  return x.length===y.length && x.length>=20 && timingSafeEqual(x,y);
};
async function github(route,method="GET",body=null){
  const res=await fetch("https://api.github.com/repos/"+REPO+route,{
    method,
    headers:{"Authorization":"Bearer "+process.env.CLASSROOM_GITHUB_TOKEN,
      "Accept":"application/vnd.github+json",
      "X-GitHub-Api-Version":"2022-11-28",
      "User-Agent":"classroom-step-lab"},
    ...(body?{body:JSON.stringify(body)}:{})
  });
  if(!res.ok)throw new Error("GitHub API HTTP "+res.status);
  return res.status===204?null:res.json();
}
export default async function handler(req,res){
  res.setHeader("Cache-Control","no-store");
  res.setHeader("X-Content-Type-Options","nosniff");
  if(!["GET","POST"].includes(req.method))
    return json(res,405,{error:"GET/POST only"});
  const configured=Boolean(process.env.CLASSROOM_GITHUB_TOKEN &&
    process.env.CLASSROOM_LAB_ADMIN_KEY &&
    process.env.CLASSROOM_NEON_READONLY_URL);
  if(req.method==="GET")
    return json(res,200,{ready:configured,mode:configured?
      "REAL_GITHUB_ACTIONS":"READ_ONLY_EVIDENCE_ONLY",
      workflow_url:"https://github.com/"+REPO+"/actions/workflows/"+WORKFLOW});
  if(!configured)
    return json(res,503,{error:"ยังไม่เปิดสิทธิ์สั่งรัน GitHub Actions จากหน้าเว็บ; ใช้โหมดตรวจหลักฐานได้ก่อน"});
  if(!safeEquals(req.headers["x-classroom-admin-key"],
                 process.env.CLASSROOM_LAB_ADMIN_KEY))
    return json(res,403,{error:"ไม่มีสิทธิ์สั่งรัน Pipeline"});
  const {stage,batch,previous_run_id}=req.body||{};
  if(!STAGES.includes(stage)||!["initial","incremental"].includes(batch)||
     !/^(0|[1-9][0-9]{0,18})$/.test(String(previous_run_id)))
    return json(res,400,{error:"ข้อมูล Step หรือ Run ID ไม่ถูกต้อง"});
  const index=STAGES.indexOf(stage),previous=String(previous_run_id);
  if((batch==="initial" && index===0)!==(previous==="0"))
    return json(res,409,{error:"Run Initial Ingest เริ่มที่ 0; Step ถัดไปต้องใช้ Run ID ของขั้นก่อน"});
  try{
    const sql=neon(process.env.CLASSROOM_NEON_READONLY_URL);
    const rows=await sql.query("SELECT phase FROM demo_control.dataset_state WHERE dataset_key='classroom'");
    const expected=batch==="initial"?"EMPTY":"RUN1_READY";
    if(rows[0]?.phase!==expected)
      return json(res,409,{error:"ข้อมูล Neon อยู่ในสถานะ "+rows[0]?.phase+
        " ไม่อนุญาตเริ่ม "+batch+" ตอนนี้; จะไม่ Reset อัตโนมัติ"});
    if(previous!=="0"){
      const prior=await github("/actions/runs/"+previous);
      const priorStage=STAGES[index===0?4:index-1];
      const prefix="Classroom ETL "+(index===0?"initial":batch)+" / "+priorStage+" / ";
      if(prior.conclusion!=="success"||prior.head_branch!==REF||
         prior.name!=="Classroom Real Pipeline - One Step"||
         typeof prior.display_title!=="string"||!prior.display_title.startsWith(prefix))
        return json(res,409,{error:"Run ID ก่อนหน้าไม่ใช่ Step ที่ผ่านจาก Branch เดียวกัน"});
    }
    await github("/actions/workflows/"+WORKFLOW+"/dispatches","POST",{
      ref:REF,inputs:{stage,batch,previous_run_id:previous}
    });
    return json(res,202,{accepted:true,execution:"REAL_GITHUB_ACTIONS",
      stage,batch,previous_run_id:previous,
      workflow_url:"https://github.com/"+REPO+"/actions/workflows/"+WORKFLOW,
      note:"GitHub รับคำขอแล้ว ยังต้องตรวจ Workflow Run และผลจริงก่อนนับว่าสำเร็จ"});
  }catch(error){
    console.error("Lab dispatch refused",error.message);
    return json(res,503,{error:"ยังไม่สามารถสั่ง GitHub Actions ได้ ("+error.message+")"});
  }
}
