/** Accept a monthly demo Source ZIP and stage it privately for the next Lab run. */
import { randomUUID } from "node:crypto";
import { unzipSync, strFromU8 } from "fflate";
import { S3Client, PutObjectCommand, GetObjectCommand, HeadObjectCommand,
  DeleteObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import sourceContract from "../dashboard/data/classroom_source_contract.json" with { type: "json" };

const TABLES=sourceContract.source_tables;
const MAX_UPLOAD=4*1024*1024,MAX_UNCOMPRESSED=24*1024*1024,MAX_FILES=24;
const json=(res,status,value)=>res.status(status).json(value);
const storage=()=>new S3Client({region:process.env.CLASSROOM_STORAGE_REGION||"us-east-2",
  endpoint:process.env.CLASSROOM_STORAGE_ENDPOINT,forcePathStyle:true,
  credentials:{accessKeyId:process.env.CLASSROOM_STORAGE_KEY_ID,
    secretAccessKey:process.env.CLASSROOM_STORAGE_SECRET}});
const key=id=>"classroom-source-uploads/"+id+".zip";
function inspectCentralDirectory(bytes){
  const min=Math.max(0,bytes.length-65557);let eocd=-1;
  for(let i=bytes.length-22;i>=min;i--){if(bytes.readUInt32LE(i)===0x06054b50){eocd=i;break;}}
  if(eocd<0)throw Error("ZIP เสียหายหรืออ่านไม่ได้");
  const count=bytes.readUInt16LE(eocd+10),size=bytes.readUInt32LE(eocd+12);
  let offset=bytes.readUInt32LE(eocd+16);
  if(!count||count>MAX_FILES||offset+size>eocd)throw Error("จำนวนไฟล์ใน ZIP ไม่ถูกต้อง");
  const entries=[];let total=0;
  for(let n=0;n<count;n++){
    if(bytes.readUInt32LE(offset)!==0x02014b50)throw Error("รายการไฟล์ใน ZIP ไม่ถูกต้อง");
    const flags=bytes.readUInt16LE(offset+8),compressed=bytes.readUInt32LE(offset+20);
    const expanded=bytes.readUInt32LE(offset+24),nameLength=bytes.readUInt16LE(offset+28);
    const extraLength=bytes.readUInt16LE(offset+30),commentLength=bytes.readUInt16LE(offset+32);
    if(flags&1)throw Error("ไม่รองรับ ZIP ที่ตั้งรหัสผ่าน");
    if(expanded>MAX_UNCOMPRESSED||(total+=expanded)>MAX_UNCOMPRESSED)
      throw Error("ขนาดข้อมูลหลังคลาย ZIP ใหญ่เกินกำหนด");
    const name=bytes.subarray(offset+46,offset+46+nameLength).toString("utf8");
    if(!name||name.includes("/")||name.includes("\\")||name==="."||name==="..")
      throw Error("ZIP ต้องวางไฟล์ตารางไว้ที่ระดับบนสุด");
    entries.push(name);offset+=46+nameLength+extraLength+commentLength;
    if(compressed>MAX_UPLOAD)throw Error("ไฟล์ใน ZIP ใหญ่เกินกำหนด");
  }
  return entries;
}
async function readBody(req){
  const chunks=[];let size=0;
  for await(const chunk of req){size+=chunk.length;if(size>MAX_UPLOAD)throw Error("ZIP ต้องมีขนาดไม่เกิน 4 MB");chunks.push(chunk);}
  return Buffer.concat(chunks);
}
function configured(){return Boolean(process.env.CLASSROOM_STORAGE_BUCKET&&
  process.env.CLASSROOM_STORAGE_ENDPOINT&&process.env.CLASSROOM_STORAGE_KEY_ID&&
  process.env.CLASSROOM_STORAGE_SECRET);}
function validId(value){return typeof value==="string"&&/^[0-9a-f-]{36}$/.test(value);}

export const config={api:{bodyParser:false}};
export default async function handler(req,res){
  res.setHeader("Cache-Control","no-store");
  res.setHeader("X-Content-Type-Options","nosniff");
  if(!["POST","GET","DELETE"].includes(req.method))return json(res,405,{error:"รองรับเฉพาะการอัปโหลดและรับไฟล์ชั่วคราว"});
  if(!configured())return json(res,503,{error:"พื้นที่พัก Source ยังไม่พร้อมใช้งาน"});
  const s3=storage(),bucket=process.env.CLASSROOM_STORAGE_BUCKET;
  if(req.method==="POST"){
    try{
      if(!String(req.headers["content-type"]||"").toLowerCase().includes("application/zip"))
        return json(res,415,{error:"กรุณาเลือก ZIP ของ Source รายเดือน"});
      const bytes=await readBody(req);
      const names=inspectCentralDirectory(bytes);
      const files=unzipSync(bytes);
      const manifestBytes=files["source_manifest.json"];
      if(!manifestBytes)throw Error("ไม่พบ source_manifest.json ใน ZIP");
      const manifest=JSON.parse(strFromU8(manifestBytes));
      if(manifest.classification!=="SYNTHETIC_EDUCATIONAL_NOT_TIKTOK"||
         !/^2026-(0[1-9]|10)$/.test(manifest.month||"")||
         !Array.isArray(manifest.source_tables)||
         JSON.stringify(manifest.source_tables)!==JSON.stringify(TABLES))
        throw Error("ZIP นี้ไม่ใช่ชุด Source รายเดือนตามโครงสร้าง ER ที่รองรับ");
      const expected=[...TABLES.map(name=>name+".csv"),"source_manifest.json"].sort();
      if(JSON.stringify([...names].sort())!==JSON.stringify(expected))
        throw Error("จำนวนหรือชื่อไฟล์ใน ZIP ไม่ครบตามชุด Source (21 ตาราง + manifest)");
      for(const table of TABLES){
        const expectedColumns=sourceContract.columns?.[table];
        const content=files[table+".csv"];
        if(!Array.isArray(expectedColumns)||!content)throw Error("ข้อมูลตาราง "+table+" ไม่ครบ");
        const header=strFromU8(content).replace(/^\uFEFF/,"").split(/\r?\n/,1)[0]
          .split(",").map(x=>x.trim().replace(/^"|"$/g,""));
        if(JSON.stringify(header)!==JSON.stringify(expectedColumns))
          throw Error("หัวคอลัมน์ใน "+table+" ไม่ตรงกับโครงสร้าง ER");
        if(JSON.stringify(manifest.columns?.[table])!==JSON.stringify(expectedColumns))
          throw Error("โครงสร้างใน manifest ของ "+table+" ไม่ตรงกับ ER");
      }
      const id=randomUUID(),uploadedAt=new Date().toISOString();
      await s3.send(new PutObjectCommand({Bucket:bucket,Key:key(id),Body:bytes,
        ContentLength:bytes.length,ContentType:"application/zip",
        Metadata:{month:manifest.month,uploaded_at:uploadedAt}}));
      return json(res,201,{upload_id:id,month:manifest.month,
        message:"ตรวจชื่อไฟล์และหัวคอลัมน์ครบแล้ว · ระบบจะตรวจข้อมูลซ้ำและความสัมพันธ์ก่อนนำเข้า"});
    }catch(error){
      console.warn("Monthly Source upload rejected:",error?.message||"invalid archive");
      return json(res,400,{error:error?.message||"อ่าน ZIP ไม่สำเร็จ"});
    }
  }
  const id=String(req.query?.id||"");
  if(!validId(id))return json(res,400,{error:"รหัสชุด Source ไม่ถูกต้อง"});
  try{
    const objectKey=key(id),head=await s3.send(new HeadObjectCommand({Bucket:bucket,Key:objectKey}));
    const uploadedAt=Date.parse(head.Metadata?.uploaded_at||"");
    if(!Number.isFinite(uploadedAt)||Date.now()-uploadedAt>24*60*60*1000){
      await s3.send(new DeleteObjectCommand({Bucket:bucket,Key:objectKey}));
      return json(res,410,{error:"ไฟล์อัปโหลดหมดอายุแล้ว กรุณาอัปโหลดใหม่"});
    }
    if(req.method==="GET"){
      const url=await getSignedUrl(s3,new GetObjectCommand({Bucket:bucket,Key:objectKey}),{expiresIn:180});
      return json(res,200,{url,month:head.Metadata?.month||"",expires_seconds:180});
    }
    await s3.send(new DeleteObjectCommand({Bucket:bucket,Key:objectKey}));
    return json(res,200,{deleted:true});
  }catch(error){
    if(error?.$metadata?.httpStatusCode===404)return json(res,404,{error:"ไม่พบไฟล์ Source หรือไฟล์ถูกใช้ไปแล้ว"});
    console.error("Temporary Source transfer failed:",error?.name||"unknown");
    return json(res,503,{error:"รับส่ง ZIP ชั่วคราวไม่สำเร็จ"});
  }
}
