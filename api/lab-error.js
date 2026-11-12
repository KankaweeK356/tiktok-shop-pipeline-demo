/** Dispatch and read isolated, one-phase-at-a-time Error Lab runs. */
import { unzipSync, strFromU8 } from "fflate";
const REPO="KankaweeK356/tiktok-shop-pipeline-demo";
const REF="feature/classroom-demo-evidence-foundation";
const WORKFLOW="classroom-live-error.yml";
const CASES=["N01","E01","E02","T01","T02","L01"];
const url="https://github.com/"+REPO+"/actions/workflows/"+WORKFLOW;
async function github(path,method="GET",body,raw=false){
  const response=await fetch("https://api.github.com/repos/"+REPO+path,{
    method,headers:{Authorization:"Bearer "+process.env.CLASSROOM_GITHUB_TOKEN,
      Accept:"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28",
      "User-Agent":"classroom-error-lab"},
    ...(body?{body:JSON.stringify(body)}:{})});
  if(!response.ok)throw Error("GitHub HTTP "+response.status);
  if(response.status===204)return null;
  return raw?new Uint8Array(await response.arrayBuffer()):response.json();
}
const runTitle=(scenario,phase,previous)=>"Classroom Error "+scenario+
  " / "+phase+" / previous "+previous;
export default async function handler(req,res){
  res.setHeader("Cache-Control","no-store");
  if(!["GET","POST"].includes(req.method))return res.status(405).json({error:"GET/POST only"});
  if(req.method==="POST"){
    const body=typeof req.body==="string"?JSON.parse(req.body):(req.body||{});
    const phase=String(body.phase||"");
    if(phase==="reset")return res.status(200).json({ready:true});
    const scenario=String(body.case||"");
    const previous=String(body.previous_run_id||"0");
    if(!CASES.includes(scenario)||!["fail","fix"].includes(phase)||
       !/^(0|[1-9][0-9]{0,18})$/.test(previous))
      return res.status(400).json({error:"เลือกรณีทดสอบหรือขั้นตอนต่อไม่ถูกต้อง"});
    if((phase==="fail"&&previous!=="0")||(phase==="fix"&&previous==="0"))
      return res.status(409).json({error:"ต้องตรวจพบปัญหาก่อน จึงสั่งให้ระบบแก้และตรวจซ้ำได้"});
    if(!process.env.CLASSROOM_GITHUB_TOKEN||!process.env.CLASSROOM_LAB_WRITER_URL)
      return res.status(503).json({error:"Error Lab ยังไม่พร้อม"});
    try{
      const recent=await github("/actions/workflows/"+WORKFLOW+
        "/runs?branch="+encodeURIComponent(REF)+"&event=workflow_dispatch&per_page=20");
      if((recent.workflow_runs||[]).some(run=>run.status!=="completed"))
        return res.status(409).json({error:"มีการทดสอบ Error กำลังรันอยู่ กรุณารอให้จบก่อน"});
      if(phase==="fix"){
        const prior=await github("/actions/runs/"+previous);
        if(prior.head_branch!==REF||prior.path!==".github/workflows/"+WORKFLOW||
           prior.event!=="workflow_dispatch"||prior.conclusion!=="success"||
           prior.display_title!==runTitle(scenario,"fail","0"))
          return res.status(409).json({error:"ไม่พบผลตรวจปัญหาที่ตรงกับกรณีนี้ กรุณาเริ่มทดสอบกรณีนี้ใหม่"});
      }
      await github("/actions/workflows/"+WORKFLOW+"/dispatches","POST",{
        ref:REF,inputs:{case:scenario,phase,previous_run_id:previous}});
      return res.status(202).json({accepted:true,url,phase,case:scenario});
    }catch(error){
      console.error("Error lab dispatch failed",error?.message);
      return res.status(503).json({error:"สั่งงาน GitHub Actions ไม่สำเร็จ · ตรวจการเชื่อมต่อแล้วลองอีกครั้ง"});
    }
  }
  if(!process.env.CLASSROOM_GITHUB_TOKEN)
    return res.status(503).json({error:"ยังอ่านผล Error Lab ไม่ได้"});
  try{
    const scenario=String(req.query?.case||"");
    const phase=String(req.query?.phase||"");
    const previous=String(req.query?.previous_run_id||"0");
    const since=Date.parse(String(req.query?.since||""));
    if(!CASES.includes(scenario)||!["fail","fix"].includes(phase)||
       !/^(0|[1-9][0-9]{0,18})$/.test(previous)||!Number.isFinite(since))
      return res.status(400).json({error:"ข้อมูลติดตามผลทดสอบไม่ครบ"});
    const recent=await github("/actions/workflows/"+WORKFLOW+
      "/runs?branch="+encodeURIComponent(REF)+"&event=workflow_dispatch&per_page=20");
    const run=(recent.workflow_runs||[]).find(item=>
      item.display_title===runTitle(scenario,phase,previous)&&
      Date.parse(item.created_at)>=since-10000);
    if(!run)return res.status(200).json({found:false,status:"queued",url});
    const result={found:true,run_id:run.id,status:run.status,
      conclusion:run.conclusion,url:run.html_url};
    if(run.conclusion!=="success")return res.status(200).json(result);
    const listing=await github("/actions/runs/"+run.id+"/artifacts?per_page=20");
    const artifact=(listing.artifacts||[]).find(x=>x.name==="classroom-error-result"&&!x.expired);
    if(!artifact)return res.status(200).json(result);
    const files=unzipSync(await github("/actions/artifacts/"+artifact.id+"/zip","GET",null,true));
    const key=Object.keys(files).find(x=>x==="classroom_error_result.json"||
      x.endsWith("/classroom_error_result.json"));
    if(key){
      const evidence=JSON.parse(strFromU8(files[key]));
      if(evidence.mode==="REAL_ISOLATED_ERROR_TEST"&&evidence.status==="SUCCESS"&&
         evidence.case===scenario&&evidence.phase===phase)
        result.evidence=evidence;
    }
    return res.status(200).json(result);
  }catch(error){
    console.error("Error lab result request failed",error?.message);
    return res.status(503).json({error:"อ่านผลจาก GitHub Actions ไม่สำเร็จ"});
  }
}
