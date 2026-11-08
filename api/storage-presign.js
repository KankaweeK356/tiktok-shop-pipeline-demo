/** Signed transfers into Neon Object Storage for a GitHub Actions job.
 *  A random token is written as a SHA256 hash to demo_control.upload_sessions
 *  by the GitHub runner with its database writer role. Only the runner knows
 *  the plaintext token. Vercel holds separate branch-scoped S3 credentials.
 *
 *  No user SQL, S3 credentials or database passwords are ever sent to browser.
 *  This endpoint is for authenticated CI only, NOT public UI uploads.
 */
import { createHash } from "node:crypto";
import { neon } from "@neondatabase/serverless";
import { S3Client, PutObjectCommand, GetObjectCommand, HeadObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

const MAX_TOKEN = 128;
const safeKey = key =>
  typeof key === "string" && key.length <= 900 && !key.startsWith("/") &&
  !key.includes("\\") && !key.includes("..") &&
  /^[A-Za-z0-9][A-Za-z0-9_./-]*$/.test(key);
const plainError = message => ({error:message});
const client = () => new S3Client({
  region: process.env.CLASSROOM_STORAGE_REGION,
  endpoint: process.env.CLASSROOM_STORAGE_ENDPOINT,
  forcePathStyle: true,
  credentials: {
    accessKeyId: process.env.CLASSROOM_STORAGE_KEY_ID,
    secretAccessKey: process.env.CLASSROOM_STORAGE_SECRET,
  },
});

export default async function handler(req,res){
  res.setHeader("Cache-Control","no-store");
  res.setHeader("X-Content-Type-Options","nosniff");
  if(req.method!=="POST")return res.status(405).json(plainError("POST only"));
  const database=process.env.CLASSROOM_NEON_READONLY_URL;
  const bucket=process.env.CLASSROOM_STORAGE_BUCKET;
  if(!database||!bucket||!process.env.CLASSROOM_STORAGE_SECRET||
    !process.env.CLASSROOM_STORAGE_KEY_ID||!process.env.CLASSROOM_STORAGE_ENDPOINT)
    return res.status(503).json(plainError("Storage not configured for this preview"));
  const {token,key,operation="upload",bytes} = req.body||{};
  if(typeof token!=="string"||token.length>MAX_TOKEN||
     !/^[a-f0-9]{64}$/.test(token)||!safeKey(key)||
     !["upload","download","head"].includes(operation))
    return res.status(400).json(plainError("Invalid request"));
  try{
    const sql=neon(database);
    const digest=createHash("sha256").update(token).digest("hex");
    const result=await sql.query(
      `SELECT s.allowed_prefix,s.max_object_bytes
       FROM demo_control.upload_sessions s
       JOIN demo_control.pipeline_runs r ON s.run_id=r.run_id
       WHERE s.token_sha256=$1 AND s.revoked=FALSE AND s.expires_at>NOW()
         AND r.status IN ('RUNNING','SUCCEEDED') LIMIT 1`,[digest]);
    if(!result.length)return res.status(403).json(plainError("Expired or unauthorized transfer"));
    const session=result[0];
    if(!key.startsWith(session.allowed_prefix))
      return res.status(403).json(plainError("Object path outside authorized run"));
    const s3=client();
    const target={Bucket:bucket,Key:key};
    if(operation==="head"){
      const metadata=await s3.send(new HeadObjectCommand(target));
      return res.status(200).json({exists:true,bytes:metadata.ContentLength,
        content_type:metadata.ContentType,key});
    }
    if(operation==="upload"){
      if(!Number.isSafeInteger(bytes)||bytes<=0||bytes>Number(session.max_object_bytes))
        return res.status(400).json(plainError("Invalid object size"));
      const command=new PutObjectCommand({...target,ContentType:"application/octet-stream",
        ContentLength:bytes});
      const url=await getSignedUrl(s3,command,{expiresIn:120});
      return res.status(200).json({url,method:"PUT",
        headers:{"content-type":"application/octet-stream"},expires_seconds:120});
    }
    const url=await getSignedUrl(s3,new GetObjectCommand(target),{expiresIn:120});
    return res.status(200).json({url,method:"GET",expires_seconds:120});
  }catch(err){
    console.error("Storage transfer error",err?.name||"unknown");
    return res.status(503).json(plainError("Cannot complete storage transfer"));
  }
}
