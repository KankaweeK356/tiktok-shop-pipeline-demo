/** Explicit new-cycle request for the isolated classroom lab only. */
import { timingSafeEqual } from "node:crypto";
import { neon } from "@neondatabase/serverless";

const repo="KankaweeK356/tiktok-shop-pipeline-demo";
const ref="feature/classroom-demo-evidence-foundation";
const workflow="classroom-live-reset.yml";
const equals=(a,b)=>{const x=Buffer.from(a||""),y=Buffer.from(b||"");
  return x.length>=20&&x.length===y.length&&timingSafeEqual(x,y);};
async function github(path,method="GET",body){
  const response=await fetch("https://api.github.com/repos/"+repo+path,{
    method,headers:{Authorization:"Bearer "+process.env.CLASSROOM_GITHUB_TOKEN,
      Accept:"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28",
      "User-Agent":"classroom-live-lab"},
    ...(body?{body:JSON.stringify(body)}:{})});
  if(!response.ok)throw Error("GitHub HTTP "+response.status);
  return response.status===204?null:response.json();
}
export default async function handler(req,res){
  res.setHeader("Cache-Control","no-store");
  if(!["GET","POST"].includes(req.method))return res.status(405).json({error:"GET/POST only"});
  if(!process.env.CLASSROOM_GITHUB_TOKEN||!process.env.CLASSROOM_LAB_NEON_URL||
     !equals(req.headers["x-classroom-admin-key"],process.env.CLASSROOM_LAB_ADMIN_KEY))
    return res.status(403).json({error:"ไม่มีสิทธิ์จัดการรอบข้อมูล"});
  try{
    if(req.method==="GET"){
      const cycle=String(req.query?.cycle||"");
      const since=Date.parse(String(req.query?.since||""));
      if(!/^[1-9][0-9]{0,8}$/.test(cycle)||!Number.isFinite(since))
        return res.status(400).json({error:"ข้อมูลติดตามไม่ถูกต้อง"});
      const runs=await github("/actions/workflows/"+workflow+
        "/runs?branch="+encodeURIComponent(ref)+"&event=workflow_dispatch&per_page=30");
      const run=(runs.workflow_runs||[]).find(item=>
        item.display_title==="Classroom lab reset / cycle "+cycle&&
        Date.parse(item.created_at)>=since-10000);
      return res.status(200).json({found:Boolean(run),status:run?.status||"queued",
        conclusion:run?.conclusion||null,url:run?.html_url||null});
    }
    const {confirmation,expected_cycle}=req.body||{};
    if(confirmation!=="RESET-DEMO-DATA"||
       !Number.isSafeInteger(expected_cycle)||expected_cycle<1)
      return res.status(400).json({error:"ต้องยืนยัน RESET-DEMO-DATA และรอบข้อมูลที่ถูกต้อง"});
    const sql=neon(process.env.CLASSROOM_LAB_NEON_URL);
    const [state]=await sql.query("SELECT phase,cycle_number FROM demo_control.dataset_state WHERE dataset_key='classroom'");
    if(state?.phase!=="RUN2_READY"||Number(state.cycle_number)!==expected_cycle)
      return res.status(409).json({error:"เคลียร์ได้เมื่อ Run 2 จบ และรอบข้อมูลยังตรงกันเท่านั้น"});
    await github("/actions/workflows/"+workflow+"/dispatches","POST",{
      ref,inputs:{expected_cycle:String(expected_cycle)}});
    return res.status(202).json({accepted:true,cycle:expected_cycle,
      workflow_url:"https://github.com/"+repo+"/actions/workflows/"+workflow});
  }catch(error){
    console.error("Lab reset request failed",error?.message);
    return res.status(503).json({error:"สั่งงาน Lab ไม่สำเร็จ กรุณาดูสถานะ GitHub Actions"});
  }
}

