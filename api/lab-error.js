/** Dispatch and read real error-recovery tests. The worker rolls back Neon probes. */
import { unzipSync, strFromU8 } from "fflate";
import { neon } from "@neondatabase/serverless";
const REPO="KankaweeK356/tiktok-shop-pipeline-demo";
const REF="feature/classroom-demo-evidence-foundation";
const WORKFLOW="classroom-live-error.yml";
const url="https://github.com/"+REPO+"/actions/workflows/"+WORKFLOW;
const CASES=["N01","E01","E02","T01","T02","L01"];
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
export default async function handler(req,res){
  res.setHeader("Cache-Control","no-store");
  if(!["GET","POST"].includes(req.method))return res.status(405).json({error:"GET/POST only"});
  if(!process.env.CLASSROOM_GITHUB_TOKEN||!process.env.CLASSROOM_ERROR_LAB_WRITER_URL)
    return res.status(503).json({error:"Lab ยังไม่พร้อม"});
  try{
    if(req.method==="GET"&&req.query?.table==="1"){
      const sql=neon(process.env.CLASSROOM_ERROR_LAB_WRITER_URL);
      const rows=await sql.query(
        'SELECT "SKU_ID","Product_Group_ID","SKU_Name" FROM demo_er1."Dim_SKU" '+
        'WHERE "SKU_ID"=$1 LIMIT 1',["ERROR_TEST_SKU"]);
      return res.status(200).json({branch:"classroom-error-lab",
        table:"demo_er1.Dim_SKU",rows});
    }
    if(req.method==="POST"){
      if(req.body?.phase==="reset"){
        const recent=await github("/actions/workflows/"+WORKFLOW+
          "/runs?branch="+encodeURIComponent(REF)+"&event=workflow_dispatch&per_page=10");
        if((recent.workflow_runs||[]).some(run=>run.status!=="completed"))
          return res.status(409).json({error:"รอการทดสอบปัจจุบันให้จบก่อน"});
        const sql=neon(process.env.CLASSROOM_ERROR_LAB_WRITER_URL);
        await sql.query('DELETE FROM demo_er1."Dim_SKU" WHERE "SKU_ID"=$1',
          ["ERROR_TEST_SKU"]);
        return res.status(200).json({ready:true,branch:"classroom-error-lab"});
      }
      const selected=String(req.body?.case||"");
      const phase=String(req.body?.phase||"");
      const previous=String(req.body?.previous_run_id||"");
      if(!CASES.includes(selected))return res.status(400).json({error:"เลือกกรณี Error ไม่ถูกต้อง"});
      if(!["fail","fix"].includes(phase)||!/^(0|[1-9][0-9]{0,18})$/.test(previous)||
         (phase==="fail")!==(previous==="0"))
        return res.status(400).json({error:"ลำดับการทดสอบไม่ถูกต้อง"});
      if(phase==="fix"){
        const prior=await github("/actions/runs/"+previous);
        if(prior.head_branch!==REF||prior.path!==".github/workflows/"+WORKFLOW||
           prior.conclusion!=="success"||
           prior.display_title!=="Classroom error "+selected+" / fail / previous 0")
          return res.status(409).json({error:"ต้องรันให้พบ Error ของกรณีนี้ก่อน"});
      }
      const recent=await github("/actions/workflows/"+WORKFLOW+
        "/runs?branch="+encodeURIComponent(REF)+"&event=workflow_dispatch&per_page=10");
      if((recent.workflow_runs||[]).some(run=>run.status!=="completed"))
        return res.status(409).json({error:"มีการทดสอบ Error กำลังรันอยู่"});
      await github("/actions/workflows/"+WORKFLOW+"/dispatches","POST",
        {ref:REF,inputs:{case:selected,phase,previous_run_id:previous}});
      return res.status(202).json({accepted:true,url});
    }
    const since=Date.parse(String(req.query?.since||""));
    const selected=String(req.query?.case||"");
    const phase=String(req.query?.phase||"");
    const previous=String(req.query?.previous_run_id||"");
    if(!Number.isFinite(since)||!CASES.includes(selected)||
       !["fail","fix"].includes(phase)||!/^(0|[1-9][0-9]{0,18})$/.test(previous))
      return res.status(400).json({error:"เวลาหรือกรณีติดตามไม่ถูกต้อง"});
    const recent=await github("/actions/workflows/"+WORKFLOW+
      "/runs?branch="+encodeURIComponent(REF)+"&event=workflow_dispatch&per_page=20");
    const run=(recent.workflow_runs||[]).find(item=>
      item.display_title==="Classroom error "+selected+" / "+phase+" / previous "+previous&&
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
      if(evidence.mode==="REAL_ISOLATED_ERROR_TEST"&&evidence.case===selected&&
         evidence.phase===phase&&
         evidence.status===(phase==="fail"?"EXPECTED_ERROR":"SUCCESS"))
        result.evidence=evidence;
    }
    return res.status(200).json(result);
  }catch(error){
    console.error("Error lab request failed",error?.message);
    return res.status(503).json({error:"ติดต่อ GitHub Actions ไม่สำเร็จ"});
  }
}
