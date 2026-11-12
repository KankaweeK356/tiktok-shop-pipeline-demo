/** Download only the CSV archive from a verified completed classroom run. */
import { unzipSync } from "fflate";
const REPO="KankaweeK356/tiktok-shop-pipeline-demo";
const REF="feature/classroom-demo-evidence-foundation";
async function github(path,raw=false){
  const response=await fetch("https://api.github.com/repos/"+REPO+path,{
    headers:{Authorization:"Bearer "+process.env.CLASSROOM_GITHUB_TOKEN,
      Accept:"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28",
      "User-Agent":"classroom-warehouse-export"}});
  if(!response.ok)throw Error("GitHub HTTP "+response.status);
  return raw?new Uint8Array(await response.arrayBuffer()):response.json();
}
export default async function handler(req,res){
  res.setHeader("Cache-Control","no-store");
  if(req.method!=="GET")return res.status(405).json({error:"GET only"});
  if(!process.env.CLASSROOM_GITHUB_TOKEN)return res.status(503).json({error:"Lab ยังไม่พร้อม"});
  const id=String(req.query?.run_id||"");
  if(!/^[1-9][0-9]{0,18}$/.test(id))return res.status(400).json({error:"Run ID ไม่ถูกต้อง"});
  try{
    const run=await github("/actions/runs/"+id);
    if(run.head_branch!==REF||run.path!==".github/workflows/classroom-live-batch.yml"||
       run.conclusion!=="success")return res.status(409).json({error:"Run ยังไม่ผ่าน"});
    const listing=await github("/actions/runs/"+id+"/artifacts?per_page=30");
    const artifact=(listing.artifacts||[]).find(x=>x.name==="classroom-warehouse-csv"&&!x.expired);
    if(!artifact)return res.status(404).json({error:"ไฟล์ Warehouse หมดอายุหรือยังไม่พร้อม"});
    if(artifact.size_in_bytes>30*1024*1024)return res.status(413).json({error:"ไฟล์ใหญ่เกินขนาดดาวน์โหลด"});
    const files=unzipSync(await github("/actions/artifacts/"+artifact.id+"/zip",true));
    const key=Object.keys(files).find(x=>x==="warehouse_csv.zip"||x.endsWith("/warehouse_csv.zip"));
    if(!key)return res.status(404).json({error:"ไม่พบไฟล์ Warehouse"});
    res.setHeader("Content-Type","application/zip");
    res.setHeader("Content-Disposition",'attachment; filename="classroom-warehouse-run-'+id+'.zip"');
    return res.status(200).send(Buffer.from(files[key]));
  }catch(error){
    console.error("Warehouse download failed",error?.message);
    return res.status(503).json({error:"ดาวน์โหลด Warehouse ไม่สำเร็จ"});
  }
}
