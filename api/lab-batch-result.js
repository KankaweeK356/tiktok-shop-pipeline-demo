/** Read the immutable completed result, never a live database mutation. */
import { unzipSync, strFromU8 } from "fflate";
import warehouseDownload from "../lib/lab-warehouse-download.js";
const REPO="KankaweeK356/tiktok-shop-pipeline-demo";
const REF="feature/classroom-demo-evidence-foundation";
async function github(path,raw=false){
  const response=await fetch("https://api.github.com/repos/"+REPO+path,{
    headers:{Authorization:"Bearer "+process.env.CLASSROOM_GITHUB_TOKEN,
      Accept:"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28",
      "User-Agent":"classroom-complete-lab"}});
  if(!response.ok)throw Error("GitHub HTTP "+response.status);
  return raw?new Uint8Array(await response.arrayBuffer()):response.json();
}
export default async function handler(req,res){
  if(req.query?.download==="warehouse")return warehouseDownload(req,res);
  res.setHeader("Cache-Control","no-store");
  if(req.method!=="GET")return res.status(405).json({error:"GET only"});
  if(!process.env.CLASSROOM_GITHUB_TOKEN)return res.status(503).json({error:"Lab ยังไม่พร้อม"});
  const id=String(req.query?.run_id||"");
  const stage=String(req.query?.stage||"");
  if(!/^[1-9][0-9]{0,18}$/.test(id))return res.status(400).json({error:"Run ID ไม่ถูกต้อง"});
  if(stage&&!(["ingest","extract","transform","load","validate"].includes(stage)))
    return res.status(400).json({error:"Step ไม่ถูกต้อง"});
  try{
    const run=await github("/actions/runs/"+id);
    if(run.head_branch!==REF||run.path!==".github/workflows/classroom-live-batch.yml"||
       run.event!=="workflow_dispatch"||(!stage&&run.conclusion!=="success"))
      return res.status(409).json({error:"Run นี้ยังไม่สำเร็จหรือไม่ใช่ Lab ที่เลือก"});
    const listing=await github("/actions/runs/"+id+"/artifacts?per_page=30");
    const artifactName=stage?"classroom-stage-"+stage:"classroom-batch-result";
    const artifact=(listing.artifacts||[]).find(x=>x.name===artifactName&&!x.expired);
    if(!artifact)return res.status(404).json({error:"ผล Run หมดอายุหรือยังไม่พร้อม"});
    if(artifact.size_in_bytes>5*1024*1024)
      return res.status(413).json({error:"ผล Run ใหญ่เกินขนาดตัวอย่าง"});
    const files=unzipSync(await github("/actions/artifacts/"+artifact.id+"/zip",true));
    const filename=stage?"last_step_result.json":"batch_result.json";
    const key=Object.keys(files).find(x=>x===filename||x.endsWith("/"+filename));
    if(!key)return res.status(404).json({error:"ไม่พบไฟล์ผล Run"});
    const result=JSON.parse(strFromU8(files[key]));
    if(stage){
      if(result.stage!==stage||result.evidence?.mode!=="REAL_GITHUB_ACTIONS_STAGE"||
         result.evidence?.classification!=="SYNTHETIC_EDUCATIONAL_NOT_TIKTOK")
        return res.status(409).json({error:"หลักฐาน Step ไม่ตรงกัน"});
      return res.status(200).json({run_id:id,stage,evidence:result.evidence});
    }
    if(result.status!=="SUCCESS"||!Array.isArray(result.stages)||result.stages.length!==5||
       result.stages.some(x=>x.evidence?.classification!=="SYNTHETIC_EDUCATIONAL_NOT_TIKTOK"))
      return res.status(409).json({error:"หลักฐานผล Run ไม่ครบ"});
    return res.status(200).json({run_id:id,result});
  }catch(error){
    console.error("Batch result fetch failed",error?.message);
    return res.status(503).json({error:"อ่านผล Run ไม่สำเร็จ"});
  }
}
