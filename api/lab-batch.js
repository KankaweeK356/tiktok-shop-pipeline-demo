/** Dispatch and follow one complete run on the isolated classroom Neon branch. */
import { neon } from "@neondatabase/serverless";

const REPO="KankaweeK356/tiktok-shop-pipeline-demo";
const REF="feature/classroom-demo-evidence-foundation";
const WORKFLOW="classroom-live-batch.yml";
const DELIVERIES=["initial",...Array.from({length:6},(_,i)=>"incremental_"+String(i+1).padStart(2,"0"))];
const url="https://github.com/"+REPO+"/actions/workflows/"+WORKFLOW;
async function github(path,method="GET",body){
  const response=await fetch("https://api.github.com/repos/"+REPO+path,{
    method,headers:{Authorization:"Bearer "+process.env.CLASSROOM_GITHUB_TOKEN,
      Accept:"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28",
      "User-Agent":"classroom-complete-lab"},
    ...(body?{body:JSON.stringify(body)}:{})});
  if(!response.ok)throw Error("GitHub HTTP "+response.status);
  return response.status===204?null:response.json();
}
export default async function handler(req,res){
  res.setHeader("Cache-Control","no-store");
  if(!["GET","POST"].includes(req.method))return res.status(405).json({error:"GET/POST only"});
  if(!process.env.CLASSROOM_GITHUB_TOKEN||!process.env.CLASSROOM_LAB_NEON_URL||
     !process.env.CLASSROOM_LAB_WRITER_URL)
    return res.status(503).json({error:"Lab ยังไม่พร้อม"});
  try{
    const sql=neon(process.env.CLASSROOM_LAB_NEON_URL);
    if(req.method==="GET"){
      const batch=String(req.query?.batch||"");
      if(!batch){
        const [lab,orders,active,completed]=await Promise.all([
          sql.query(`SELECT d.phase,d.cycle_number,r.status AS last_run_status,
                    r.run_type AS last_run_type,r.runner_ref
                    FROM demo_control.dataset_state d
                    LEFT JOIN demo_control.pipeline_runs r ON r.run_id=d.last_run_id
                    WHERE d.dataset_key='classroom' LIMIT 1`),
          sql.query('SELECT COUNT(*)::int AS n FROM demo_er1."Fact_Orders"'),
          sql.query("SELECT run_type FROM demo_control.pipeline_runs WHERE dataset_key='classroom' AND status='RUNNING' ORDER BY started_at DESC LIMIT 1"),
          sql.query("SELECT COUNT(*)::int AS n FROM demo_control.pipeline_runs WHERE dataset_key='classroom' AND cycle_number=(SELECT cycle_number FROM demo_control.dataset_state WHERE dataset_key='classroom') AND status='SUCCEEDED' AND run_type IN ('RUN1','RUN2')")]);
        const recent=await github("/actions/workflows/"+WORKFLOW+
          "/runs?branch="+encodeURIComponent(REF)+"&event=workflow_dispatch&per_page=30");
        const workflowActive=(recent.workflow_runs||[]).find(run=>
          /^Classroom complete (initial|incremental(?:_0[1-6])?) \/ previous /.test(run.display_title||"")&&
          ["queued","in_progress","waiting","pending"].includes(run.status));
        let activeStage=null;
        if(workflowActive){
          const jobs=await github("/actions/runs/"+workflowActive.id+"/jobs?per_page=20");
          const steps=(jobs.jobs||[]).flatMap(job=>job.steps||[])
            .filter(step=>/^[1-5] /.test(step.name));
          const current=steps.find(step=>step.status==="in_progress")||
            steps.find(step=>step.status==="queued");
          activeStage=current?{name:current.name,status:current.status,
            started_at:current.started_at}:null;
        }
        const history=(recent.workflow_runs||[]).filter(run=>
          run.conclusion==="success"&&
          /^Classroom complete (initial|incremental(?:_0[1-6])?) \/ previous /.test(run.display_title||""))
          .slice(0,10).map(run=>({run_id:run.id,
            batch:run.display_title.includes(" complete initial ")?"initial":"incremental",
            created_at:run.created_at}));
        const resumeBatch=active[0]?.run_type==="RUN1"?"initial":
          active[0]?.run_type==="RUN2"?"incremental":null;
        const successCount=Number(completed[0]?.n||0);
        const nextSource=DELIVERIES[successCount]||null;
        const failed=resumeBatch&&nextSource?(recent.workflow_runs||[]).find(run=>
          run.status==="completed"&&run.conclusion!=="success"&&
          run.display_title?.startsWith("Classroom complete "+nextSource+" / previous ")):null;
        const latest=lab[0]||{};
        const githubRun=String(latest.runner_ref||"").match(/\/actions\/runs\/([1-9][0-9]*)\/?$/);
        const currentRunId=["RUN1_READY","RUN2_READY"].includes(latest.phase)&&
          latest.last_run_status==="SUCCEEDED"?githubRun?.[1]||null:null;
        return res.status(200).json({ready:true,phase:latest.phase||"UNKNOWN",
          cycle:latest.cycle_number??null,orders:orders[0]?.n??null,
          current_run_id:currentRunId,current_run_type:currentRunId?latest.last_run_type:null,
          running:Boolean(active.length||workflowActive),
          active_run_type:active[0]?.run_type||
            (workflowActive?(workflowActive.display_title.includes(" complete initial ")?"RUN1":"RUN2"):null),
          active_run_id:workflowActive?.id||null,
          active_stage:activeStage,
          previous_run_id:currentRunId,next_source_batch:nextSource,
          source_remaining:Math.max(0,DELIVERIES.length-successCount),
          source_exhausted:successCount>=DELIVERIES.length,
          resume_batch:resumeBatch,resume_run_id:failed?.id||null,history,workflow_url:url});
      }
      const since=Date.parse(String(req.query?.since||""));
      const sourceBatch=String(req.query?.source_batch||batch);
      if(!DELIVERIES.includes(sourceBatch)||!Number.isFinite(since))
        return res.status(400).json({error:"ข้อมูลติดตามไม่ถูกต้อง"});
      const runs=await github("/actions/workflows/"+WORKFLOW+
        "/runs?branch="+encodeURIComponent(REF)+"&event=workflow_dispatch&per_page=30");
      const match=(runs.workflow_runs||[]).find(run=>
        run.display_title?.startsWith("Classroom complete "+sourceBatch+" / previous ")&&
        Date.parse(run.created_at)>=since-10000);
      let stages=[];
      if(match){
        const jobs=await github("/actions/runs/"+match.id+"/jobs?per_page=20");
        stages=(jobs.jobs||[]).flatMap(job=>job.steps||[])
          .filter(step=>/^[1-5] /.test(step.name))
          .map(step=>({index:Number(step.name[0])-1,status:step.status,
            conclusion:step.conclusion,started_at:step.started_at,
            completed_at:step.completed_at}));
      }
      return res.status(200).json({found:Boolean(match),run_id:match?.id||null,stages,
        status:match?.status||"queued",conclusion:match?.conclusion||null,
        url:match?.html_url||url});
    }
    const batch=String(req.body?.batch||"");
    const previous=String(req.body?.previous_run_id||"0");
    if(!["initial","incremental"].includes(batch)||
       !/^(0|[1-9][0-9]{0,18})$/.test(previous))
      return res.status(400).json({error:"ข้อมูล Run ไม่ถูกต้อง"});
    const [state,active,completed]=await Promise.all([
      sql.query("SELECT d.phase,d.cycle_number,r.runner_ref FROM demo_control.dataset_state d LEFT JOIN demo_control.pipeline_runs r ON r.run_id=d.last_run_id WHERE d.dataset_key='classroom'"),
      sql.query("SELECT run_type FROM demo_control.pipeline_runs WHERE dataset_key='classroom' AND status IN ('RUNNING','QUEUED') LIMIT 1"),
      sql.query("SELECT COUNT(*)::int AS n FROM demo_control.pipeline_runs WHERE dataset_key='classroom' AND cycle_number=(SELECT cycle_number FROM demo_control.dataset_state WHERE dataset_key='classroom') AND status='SUCCEEDED' AND run_type IN ('RUN1','RUN2')")]);
    const sourceBatch=DELIVERIES[Number(completed[0]?.n||0)];
    if(!sourceBatch)return res.status(409).json({error:"Source ชุดนี้ใช้ครบแล้ว เคลียร์ Lab เพื่อเริ่มใหม่"});
    if(batch!==(sourceBatch==="initial"?"initial":"incremental"))
      return res.status(409).json({error:"เลือกการรันไม่ตรงกับ Source ชุดถัดไป"});
    const expected=sourceBatch==="initial"?"EMPTY":sourceBatch==="incremental_01"?"RUN1_READY":"RUN2_READY";
    if(state[0]?.phase!==expected)
      return res.status(409).json({error:"Lab ยังไม่พร้อมเริ่มรอบนี้"});
    const retry=Boolean(active.length);
    if(retry&&active[0]?.run_type!==(batch==="initial"?"RUN1":"RUN2"))
      return res.status(409).json({error:"มี Run อื่นกำลังทำงาน"});
    if((retry&&previous==="0")||(!retry&&sourceBatch==="initial"&&previous!=="0")||
       (!retry&&sourceBatch!=="initial"&&previous==="0"))
      return res.status(409).json({error:"Run ID สำหรับเริ่มหรือรันต่อไม่ถูกต้อง"});
    if(previous!=="0"){
      const prior=await github("/actions/runs/"+previous);
      const valid=prior.head_branch===REF&&prior.path===".github/workflows/"+WORKFLOW&&
        prior.event==="workflow_dispatch"&&
        (retry?prior.status==="completed"&&prior.conclusion!=="success"&&
          prior.display_title?.startsWith("Classroom complete "+sourceBatch+" / previous "):
          prior.conclusion==="success"&&
          prior.html_url===state[0]?.runner_ref);
      if(!valid)return res.status(409).json({error:"Run ก่อนหน้าไม่ตรงกับการรันต่อ"});
      if(!retry){
        const saved=await github("/actions/runs/"+previous+"/artifacts?per_page=100");
        const workspace=(saved.artifacts||[]).find(item=>
          item.name==="classroom-lab-workspace"&&!item.expired);
        if(!workspace)return res.status(409).json({error:
          "ไฟล์ข้อมูลที่ใช้เติมรอบต่อหมดอายุแล้ว (เก็บไว้ 90 วัน) กรุณาเคลียร์ Lab แล้วเริ่ม Run 1 ใหม่"});
      }
    }
    const recent=await github("/actions/workflows/"+WORKFLOW+
      "/runs?branch="+encodeURIComponent(REF)+"&event=workflow_dispatch&per_page=30");
    const title="Classroom complete "+sourceBatch+" / previous "+previous;
    if((recent.workflow_runs||[]).some(run=>run.display_title===title&&run.status!=="completed"))
      return res.status(409).json({error:"Run นี้ถูกสั่งแล้ว กรุณารอผล"});
    await github("/actions/workflows/"+WORKFLOW+"/dispatches","POST",{
      ref:REF,inputs:{batch:sourceBatch,previous_run_id:previous}});
    return res.status(202).json({accepted:true,source_batch:sourceBatch,workflow_url:url});
  }catch(error){
    console.error("Complete lab request failed",error?.message);
    return res.status(503).json({error:"ติดต่อ GitHub หรือ Neon ไม่สำเร็จ"});
  }
}

