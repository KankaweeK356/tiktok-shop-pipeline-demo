/** Dispatch one genuine GitHub Actions pipeline stage. No anonymous writes.
 * Public demo may run only the next real stage in the isolated Neon lab.
 * The server keeps the scoped GitHub token; reset remains separately protected.
 *
 * NEVER use this endpoint to reset Neon, and never pass credentials as workflow inputs.
 */
import { neon } from "@neondatabase/serverless";

const REPO="KankaweeK356/tiktok-shop-pipeline-demo";
const REF="feature/classroom-demo-evidence-foundation";
const WORKFLOW="classroom-real-step.yml";
const STAGES=["ingest","extract","transform","load","validate"];
const json=(res,code,value)=>res.status(code).json(value);
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
    process.env.CLASSROOM_LAB_NEON_URL && process.env.CLASSROOM_LAB_WRITER_URL);
  if(req.method==="GET"){
    const workflow_url="https://github.com/"+REPO+"/actions/workflows/"+WORKFLOW;
    if(!req.query?.stage){
      let lab={branch:"classroom-live-run-lab",phase:"UNKNOWN",cycle:null,orders:null};
      if(process.env.CLASSROOM_LAB_NEON_URL){
        try{
          const sql=neon(process.env.CLASSROOM_LAB_NEON_URL);
          const [state,counts,active]=await Promise.all([
            sql.query("SELECT phase,cycle_number FROM demo_control.dataset_state WHERE dataset_key='classroom'"),
            sql.query('SELECT COUNT(*)::int AS n FROM demo_er1."Fact_Orders"'),
            sql.query("SELECT runner_ref,run_type FROM demo_control.pipeline_runs WHERE dataset_key='classroom' AND status='RUNNING' ORDER BY started_at DESC LIMIT 1")
          ]);
          lab={branch:"classroom-live-run-lab",phase:state[0]?.phase||"UNKNOWN",
               cycle:state[0]?.cycle_number||null,orders:counts[0]?.n??null,
               active_run:active[0]||null};
        }catch(_error){/* No write and no credentials in response. */}
      }
      if(configured&&["EMPTY","RUN1_READY"].includes(lab.phase)){
        try{
          const runs=await github("/actions/workflows/"+WORKFLOW+
            "/runs?branch="+encodeURIComponent(REF)+"&event=workflow_dispatch&per_page=50");
          const all=runs.workflow_runs||[];
          if(lab.active_run?.runner_ref){
            const root=String(lab.active_run.runner_ref).match(/\/runs\/([1-9][0-9]*)$/)?.[1];
            const batch=lab.active_run.run_type==="RUN1"?"initial":"incremental";
            let current=all.find(run=>String(run.id)===root&&run.conclusion==="success");
            let index=current?0:-1;
            while(current&&index<STAGES.length-1){
              const nextStage=STAGES[index+1];
              const next=all.find(run=>run.conclusion==="success"&&
                run.display_title?.startsWith("Classroom ETL "+batch+" / "+nextStage+
                  " / previous "+current.id));
              if(!next)break;
              current=next;index++;
            }
            if(current&&index<STAGES.length-1){
              lab.resume_run_id=current.id;lab.resume_stage=STAGES[index+1];
              lab.resume_batch=batch;
            }
          }else if(lab.phase==="RUN1_READY"){
            const last=all.find(run=>run.conclusion==="success"&&
              run.display_title?.startsWith("Classroom ETL initial / validate / previous "));
            lab.resume_run_id=last?.id||null;
          }
        }catch(_error){lab.resume_run_id=null;}
      }
      delete lab.active_run;
      return json(res,200,{ready:configured,mode:configured?
        "REAL_GITHUB_ACTIONS":"READ_ONLY_EVIDENCE_ONLY",workflow_url,lab});
    }
    if(!configured)return json(res,503,{error:"Lab ยังไม่พร้อม"});
    const stage=req.query.stage,batch=req.query.batch,previous=String(req.query.previous_run_id||"");
    const since=Date.parse(String(req.query.since||""));
    if(!STAGES.includes(stage)||!["initial","incremental"].includes(batch)||
       !/^(0|[1-9][0-9]{0,18})$/.test(previous)||!Number.isFinite(since))
      return json(res,400,{error:"ข้อมูลติดตาม Workflow ไม่ถูกต้อง"});
    try{
      const data=await github("/actions/workflows/"+WORKFLOW+
        "/runs?branch="+encodeURIComponent(REF)+"&event=workflow_dispatch&per_page=30");
      const label="Classroom ETL "+batch+" / "+stage+" / previous "+previous;
      const match=(data.workflow_runs||[]).find(run=>
        run.display_title===label&&Date.parse(run.created_at)>=since-10000);
      return json(res,200,{found:Boolean(match),
        run_id:match?.id||null,status:match?.status||"queued",
        conclusion:match?.conclusion||null,url:match?.html_url||workflow_url,
        evidence_mode:"REAL_GITHUB_WORKFLOW"});
    }catch(error){
      console.error("Lab status lookup failed",error.message);
      return json(res,503,{error:"อ่านสถานะ GitHub Actions ไม่สำเร็จ"});
    }
  }
  if(!configured)
    return json(res,503,{error:"ยังไม่เปิดสิทธิ์สั่งรัน GitHub Actions จากหน้าเว็บ; ใช้โหมดตรวจหลักฐานได้ก่อน"});
  const {stage,batch,previous_run_id}=req.body||{};
  if(!STAGES.includes(stage)||!["initial","incremental"].includes(batch)||
     !/^(0|[1-9][0-9]{0,18})$/.test(String(previous_run_id)))
    return json(res,400,{error:"ข้อมูล Step หรือ Run ID ไม่ถูกต้อง"});
  const index=STAGES.indexOf(stage),previous=String(previous_run_id);
  if((batch==="initial" && index===0)!==(previous==="0"))
    return json(res,409,{error:"Run Initial Ingest เริ่มที่ 0; Step ถัดไปต้องใช้ Run ID ของขั้นก่อน"});
  try{
    const sql=neon(process.env.CLASSROOM_LAB_NEON_URL);
    const [rows,active]=await Promise.all([
      sql.query("SELECT phase FROM demo_control.dataset_state WHERE dataset_key='classroom'"),
      sql.query("SELECT run_type FROM demo_control.pipeline_runs WHERE dataset_key='classroom' AND status='RUNNING' LIMIT 1")
    ]);
    const expected=batch==="initial"?"EMPTY":"RUN1_READY";
    if(rows[0]?.phase!==expected)
      return json(res,409,{error:"ข้อมูล Neon อยู่ในสถานะ "+rows[0]?.phase+
        " ไม่อนุญาตเริ่ม "+batch+" ตอนนี้; จะไม่ Reset อัตโนมัติ"});
    if(index===0&&batch==="initial"&&active.length)
      return json(res,409,{error:"Run 1 เริ่มแล้ว ให้รันต่อจากขั้นล่าสุด"});
    if(index===0&&batch==="incremental"&&active.length)
      return json(res,409,{error:"Run 2 เริ่มแล้ว ให้รันต่อจากขั้นล่าสุด"});
    if(index>0&&active[0]?.run_type!==(batch==="initial"?"RUN1":"RUN2"))
      return json(res,409,{error:"ยังไม่มีรอบที่กำลังทำงานสำหรับขั้นนี้"});
    if(previous!=="0"){
      const prior=await github("/actions/runs/"+previous);
      const priorStage=STAGES[index===0?4:index-1];
      const prefix="Classroom ETL "+(index===0?"initial":batch)+" / "+priorStage+" / ";
      if(prior.conclusion!=="success"||prior.head_branch!==REF||
         prior.path!==".github/workflows/"+WORKFLOW||
         prior.event!=="workflow_dispatch"||
         typeof prior.display_title!=="string"||!prior.display_title.startsWith(prefix))
        return json(res,409,{error:"Run ID ก่อนหน้าไม่ใช่ Step ที่ผ่านจาก Branch เดียวกัน"});
    }
    const title="Classroom ETL "+batch+" / "+stage+" / previous "+previous;
    const recent=await github("/actions/workflows/"+WORKFLOW+
      "/runs?branch="+encodeURIComponent(REF)+"&event=workflow_dispatch&per_page=50");
    if((recent.workflow_runs||[]).some(run=>run.display_title===title&&
       (run.status!=="completed"||run.conclusion==="success")))
      return json(res,409,{error:"ขั้นนี้ถูกสั่งรันแล้ว กรุณาตรวจสถานะงานเดิม"});
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
