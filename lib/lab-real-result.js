/** Read only real stage output artifact from a completed verified Actions run. */
import { unzipSync, strFromU8 } from "fflate";
const REPO="KankaweeK356/tiktok-shop-pipeline-demo";
const REF="feature/classroom-demo-evidence-foundation";
async function api(url,raw=false){
  const response=await fetch("https://api.github.com/repos/"+REPO+url,{
    headers:{"Authorization":"Bearer "+process.env.CLASSROOM_GITHUB_TOKEN,
      "Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28",
      "User-Agent":"classroom-step-lab"}});
  if(!response.ok)throw Error("GitHub HTTP "+response.status);
  return raw?new Uint8Array(await response.arrayBuffer()):response.json();
}
export default async function handler(req,res){
  res.setHeader("Cache-Control","no-store");
  if(req.method!=="GET")return res.status(405).json({error:"GET only"});
  if(!process.env.CLASSROOM_GITHUB_TOKEN)
    return res.status(503).json({error:"ยังอ่านผลการรันไม่ได้"});
  const id=String(req.query?.run_id||"");
  if(!/^[1-9][0-9]{0,18}$/.test(id))return res.status(400).json({error:"Invalid run id"});
  try{
    const run=await api("/actions/runs/"+id);
    if(run.head_branch!==REF||run.path!==".github/workflows/classroom-real-step.yml"||
      run.event!=="workflow_dispatch"||
      run.conclusion!=="success")return res.status(409).json({error:"งานนี้ไม่ใช่ Step ที่ผ่านบน Branch เป้าหมาย"});
    const catalog=await api("/actions/runs/"+id+"/artifacts?per_page=30");
    const artifact=(catalog.artifacts||[]).find(x=>x.name==="classroom-lab-result"&&!x.expired);
    if(!artifact)return res.status(404).json({error:"ยังไม่พบผลลัพธ์ Step หรือ Artifact หมดอายุ"});
    if(artifact.size_in_bytes>3*1024*1024)
      return res.status(413).json({error:"Artifact ใหญ่เกินขนาด Preview"});
    const zipped=await api("/actions/artifacts/"+artifact.id+"/zip",true);
    const files=unzipSync(zipped);
    const key=Object.keys(files).find(x=>x==="last_step_result.json"||
      x.endsWith("/last_step_result.json"));
    if(!key)return res.status(404).json({error:"ไฟล์สรุป Step ไม่อยู่ใน Artifact"});
    const result=JSON.parse(strFromU8(files[key]));
    if(result.evidence?.mode!=="REAL_GITHUB_ACTIONS_STAGE"||
       result.evidence?.classification!=="SYNTHETIC_EDUCATIONAL_NOT_TIKTOK")
      return res.status(409).json({error:"Provenance ของผลรันไม่ถูกต้อง"});
    return res.status(200).json({run_id:id,mode:"REAL_GITHUB_ACTIONS_STAGE",
      receipt:result.evidence});
  }catch(e){
    console.error("Real stage artifact fetch failed",e?.message);
    return res.status(503).json({error:"ไม่สามารถอ่านผลลัพธ์จริงจาก GitHub ได้"});
  }
}

