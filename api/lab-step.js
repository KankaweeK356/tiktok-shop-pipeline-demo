/**
 * Classroom Pipeline Lab: executes a fresh READ-ONLY verification on each click.
 * Unlike a GitHub worker this DOES NOT ingest, transform, load or reset data.
 * Reads live Neon SQL and previously archived, real Parquet/validation receipts.
 * No arbitrary SQL, object key, or filesystem path comes from the browser.
 */
import { neon } from "@neondatabase/serverless";
import { S3Client, GetObjectCommand, HeadObjectCommand } from "@aws-sdk/client-s3";
import { parquetReadObjects, parquetMetadataAsync } from "hyparquet";

const STAGES=["ingest","extract","transform","load","validate"];
const DEFAULT_SOURCE="Fact_Orders";
const MAX_BYTES=2*1024*1024; // preview files only; DuckDB is inspected via HEAD
const TABLE_NAME=/^[A-Za-z][A-Za-z0-9_]*$/;
const normalized=value=>{
  if(typeof value==="bigint")return value.toString();
  if(value instanceof Date)return value.toISOString();
  if(value instanceof Uint8Array)return "[binary]";
  if(value===undefined)return null;
  return value;
};
const cleanRow=row=>Object.fromEntries(
  Object.entries(row).map(([key,value])=>[key,normalized(value)])
);
const rounded=value=>Math.round(Number(value)*100)/100;
const storage=()=>new S3Client({
  endpoint:process.env.CLASSROOM_STORAGE_ENDPOINT,
  region:process.env.CLASSROOM_STORAGE_REGION||"us-east-2",
  forcePathStyle:true,
  credentials:{
    accessKeyId:process.env.CLASSROOM_STORAGE_KEY_ID,
    secretAccessKey:process.env.CLASSROOM_STORAGE_SECRET,
  }
});
function keyFromArchive(uri){
  const prefix="neon-storage://"+process.env.CLASSROOM_STORAGE_BUCKET+"/";
  if(!uri.startsWith(prefix))throw Error("Archive URI outside configured bucket");
  const key=uri.slice(prefix.length);
  if(!key.startsWith("recovery/cycle-1/github-42487488684/")||key.includes(".."))
    throw Error("Archive key outside verified classroom run");
  return key;
}
async function archive(sql,type,tail){
  const rows=await sql.query(`
    SELECT a.artifact_uri,a.content_sha256,a.size_bytes
      FROM demo_control.pipeline_artifacts a
      JOIN demo_control.pipeline_runs r ON r.run_id=a.run_id
      JOIN demo_control.dataset_state s ON s.dataset_key=r.dataset_key
     WHERE r.cycle_number=s.cycle_number
       AND a.artifact_type=$1
       AND a.artifact_uri LIKE $2
     ORDER BY a.created_at DESC LIMIT 1
  `,[type,"%/"+tail]);
  if(!rows.length)throw Error("No archived artifact: "+tail);
  return rows[0];
}
async function getArchiveBytes(s3,artifact){
  const expected=Number(artifact.size_bytes);
  if(!Number.isFinite(expected)||expected<1||expected>MAX_BYTES)
    throw Error("Archive is not a permitted small preview file");
  const obj=await s3.send(new GetObjectCommand({
    Bucket:process.env.CLASSROOM_STORAGE_BUCKET,
    Key:keyFromArchive(artifact.artifact_uri)
  }));
  const bytes=await obj.Body.transformToByteArray();
  if(bytes.byteLength!==expected)throw Error("Archive byte count does not match control");
  const ab=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);
  return {ab,bytes};
}
async function jsonArchive(s3,artifact){
  const {bytes}=await getArchiveBytes(s3,artifact);
  return JSON.parse(new TextDecoder().decode(bytes));
}
async function parquetPreview(s3,artifact){
  const {ab}=await getArchiveBytes(s3,artifact);
  const metadata=await parquetMetadataAsync(ab);
  const rows=await parquetReadObjects({file:ab,rowStart:0,rowEnd:5});
  return {records:Number(metadata.num_rows),columns:rows.length?Object.keys(rows[0]):[],
    preview:rows.map(cleanRow),file:artifact.artifact_uri,
    sha256:artifact.content_sha256};
}
async function sourceTable(sql,table){
  const names=await sql.query(
    "SELECT table_name FROM information_schema.tables WHERE table_schema='demo_er1' AND table_type='BASE TABLE'");
  if(!TABLE_NAME.test(table)||!names.some(x=>x.table_name===table))
    throw Error("Unknown source table");
  const quoted='"demo_er1"."'+table+'"';
  const [count,preview,columns]=await Promise.all([
    sql.query("SELECT COUNT(*)::int AS n FROM "+quoted),
    sql.query("SELECT * FROM "+quoted+" LIMIT 5"),
    sql.query("SELECT column_name FROM information_schema.columns WHERE table_schema='demo_er1' AND table_name=$1 ORDER BY ordinal_position",[table])
  ]);
  return {table,records:Number(count[0]?.n||0),
    columns:columns.map(x=>x.column_name),
    preview:preview.map(cleanRow),origin:"NEON_LIVE"};
}
async function paidTotals(sql){
  const r=await sql.query(`SELECT COUNT(*)::int AS paid_items,
  ROUND(COALESCE(SUM(COALESCE(i."Total_Selling_Amount",0)-
      COALESCE(i."Voucher_Allocated_Amount",0)),0)::numeric,2) AS net_revenue
  FROM demo_er1."Fact_Order_Items" i
  JOIN demo_er1."Fact_Orders" o ON o."Order_ID"=i."Order_ID"
 WHERE o."Current_Status" IN ('Paid','Shipped','Delivered') AND o."Paid_At" IS NOT NULL`);
  return {paid_items:Number(r[0].paid_items),net_revenue:Number(r[0].net_revenue)};
}
export default async function handler(req,res){
  res.setHeader("Cache-Control","private, no-store");
  res.setHeader("X-Content-Type-Options","nosniff");
  if(req.method!=="GET"){res.setHeader("Allow","GET");return res.status(405).json({error:"GET only"});}
  const stage=req.query?.stage;
  if(typeof stage!=="string"||!STAGES.includes(stage))
    return res.status(400).json({error:"Unknown lab step"});
  const url=process.env.CLASSROOM_NEON_READONLY_URL;
  const bucket=process.env.CLASSROOM_STORAGE_BUCKET;
  if(!url||!bucket||!process.env.CLASSROOM_STORAGE_SECRET)
    return res.status(503).json({error:"Neon/Private Storage preview not configured"});
  const out={stage,mode:"READ_ONLY_EVIDENCE_REPLAY",
    classification:"SYNTHETIC_EDUCATIONAL_NOT_TIKTOK",
    executed_at:new Date().toISOString(),checks:[],
    historical_run:"42487488684",is_new_etl_run:false,
    safety_note:"ตรวจข้อมูลและไฟล์จริงซ้ำเท่านั้น ไม่ได้สร้าง Batch หรือเขียน Neon ใหม่"};
  try{
    const sql=neon(url);
    const state=await sql.query("SELECT phase,cycle_number FROM demo_control.dataset_state WHERE dataset_key='classroom'");
    if(!state.length||state[0].phase!=="RUN2_READY"||Number(state[0].cycle_number)!==1)
      return res.status(409).json({error:"รอบข้อมูลปัจจุบันไม่ใช่ RUN2_READY รอบ 1 จึงหยุดการเล่นซ้ำเพื่อไม่แสดงผลจากรอบเก่า"});
    const s3=storage();
    if(stage==="ingest"){
      const table=typeof req.query?.table==="string"?req.query.table:DEFAULT_SOURCE;
      const source=await sourceTable(sql,table);
      const all=await sql.query("SELECT COUNT(*)::int AS n FROM information_schema.tables WHERE table_schema='demo_er1' AND table_type='BASE TABLE'");
      out.input={label:"ข้อมูล Source Database",detail:"ข้อมูลจำลองร้านเสื้อผ้าผู้หญิงที่เคยนำเข้า Neon"};
      out.process=["Query จำนวนตาราง Source จาก Neon","อ่านจำนวนแถวและ Schema ล่าสุด","เรียก SELECT 5 แถวจริงจากตารางที่เลือก"];
      out.output=source;
      out.metrics=[{label:"ตาราง ER1",value:Number(all[0].n),unit:"ตาราง"},{label:"แถวใน "+table,value:source.records,unit:"รายการ"}];
      out.checks=[{label:"ER1 มีครบ 25 ตาราง",pass:Number(all[0].n)===25}];
      out.provenance="LIVE_NEON_SOURCE_CHECK_NOT_FRESH_INGEST";
    } else if(stage==="extract"){
      const table=typeof req.query?.table==="string"?req.query.table:DEFAULT_SOURCE;
      // Only permit tables that exist in Neon before composing the fixed archive filename.
      const src=await sourceTable(sql,table);
      const file=await archive(sql,"LAKE_RAW","lake/raw/source_current/"+table+".parquet");
      const parquet=await parquetPreview(s3,file);
      out.input={label:"Neon · "+table,records:src.records,preview:src.preview};
      out.process=["ตรวจไฟล์ใน Private Neon Object Storage","อ่าน metadata ของ Parquet จริง","เทียบจำนวนแถวใน Parquet กับ SQL ปัจจุบัน"];
      out.output={...parquet,origin:"NEON_PRIVATE_RAW_PARQUET"};
      out.metrics=[{label:"Rows in Neon",value:src.records},{label:"Rows in Raw Parquet",value:parquet.records}];
      out.checks=[{label:"Raw Parquet ตรงกับ Neon",pass:src.records===parquet.records}];
      out.provenance="LIVE_SOURCE_VS_ARCHIVED_RAW_CURRENT_SNAPSHOT";
    } else if(stage==="transform"){
      const rawFile=await archive(sql,"LAKE_RAW","lake/raw/source_current/Fact_Order_Items.parquet");
      const stdFile=await archive(sql,"LAKE_STANDARDIZED","lake/standardized/incremental/Fact_Sales_Order_Item.parquet");
      const raw=await parquetPreview(s3,rawFile);
      const std=await parquetPreview(s3,stdFile);
      const totals=await paidTotals(sql);
      out.input={label:"Raw Fact_Order_Items",records:raw.records,preview:raw.preview,origin:raw.file};
      out.process=["อ่าน Raw Order Items จากไฟล์ Parquet","อ่าน Standardized Sales Fact จากไฟล์ Parquet","ยืนยันว่า Standardized มีเฉพาะรายการขายที่ชำระแล้ว"];
      out.output={...std,origin:"VERIFIED_REBUILT_STANDARDIZED_PARQUET"};
      out.metrics=[{label:"Raw order-item rows",value:raw.records},{label:"Standardized paid items",value:std.records}];
      out.checks=[{label:"จำนวน Sales Fact เท่ากับ Paid Items ใน Neon",pass:std.records===totals.paid_items}];
      out.provenance="ARCHIVED_RECONSTRUCTED_TRANSFORM_OUTPUT_NOT_NEW_ETL";
    } else if(stage==="load"){
      const warehouse=await archive(sql,"WAREHOUSE","er2.duckdb");
      const stdFile=await archive(sql,"LAKE_STANDARDIZED","lake/standardized/incremental/Fact_Sales_Order_Item.parquet");
      const std=await parquetPreview(s3,stdFile);
      const head=await s3.send(new HeadObjectCommand({
        Bucket:bucket,Key:keyFromArchive(warehouse.artifact_uri)}));
      const reportFile=await archive(sql,"REPORT","reports/functional_incremental.json");
      const report=await jsonArchive(s3,reportFile);
      const byteCount=Number(head.ContentLength);
      out.input={label:"Standardized Fact_Sales_Order_Item",records:std.records,
        preview:std.preview};
      out.process=["ตรวจสอบไฟล์ DuckDB ที่เก็บถาวร","ตรวจขนาดไฟล์จริงกับรายการใน Neon Control","อ่าน Validation Report ของ Warehouse ที่ผ่านก่อนเก็บถาวร"];
      out.output={table:"Fact_Sales_Order_Item",records:report.warehouse_sales_item_count,
        preview:[],origin:"WAREHOUSE_VERIFIED_BY_ARCHIVED_REPORT",
        file:warehouse.artifact_uri,
        note:"ตัวอย่างด้านบนมาจาก Standardized; ยังไม่ได้ Query ตาราง DuckDB โดยตรงจาก API"};
      out.metrics=[{label:"Warehouse file",value:byteCount,unit:"bytes"},
        {label:"Sales Fact rows",value:Number(report.warehouse_sales_item_count)}];
      out.checks=[
        {label:"DuckDB file exists and byte count matches archive",pass:byteCount===Number(warehouse.size_bytes)},
        {label:"Warehouse row count matches standardized",pass:Number(report.warehouse_sales_item_count)===std.records}
      ];
      out.provenance="REBUILT_DUCKDB_WITH_VERIFIED_ARCHIVE_REPORT";
    } else {
      const file=await archive(sql,"REPORT","reports/functional_incremental.json");
      const report=await jsonArchive(s3,file);
      const totals=await paidTotals(sql);
      const delta=rounded(totals.net_revenue-Number(report.er2_net_revenue));
      out.input={label:"Neon Paid Orders และ Report จาก Warehouse",records:totals.paid_items};
      out.process=["คำนวณจำนวนรายการชำระแล้วและ Net Revenue ใหม่จาก Neon","อ่าน Functional Validation Report ใน Storage","เปรียบเทียบจำนวนรายการและยอดเงินกับ Warehouse"];
      out.output={table:"Reconciliation",records:report.checks,preview:[
        {check:"Paid item count",source:totals.paid_items,warehouse:report.warehouse_sales_item_count},
        {check:"Net Revenue (THB)",source:totals.net_revenue,warehouse:report.er2_net_revenue},
        {check:"Warehouse tests",source:"—",warehouse:report.passed+" / "+report.checks}
      ],origin:"LIVE_NEON_VS_ARCHIVED_RECONSTRUCTED_WAREHOUSE_REPORT"};
      out.metrics=[{label:"Checks in report",value:Number(report.checks)},
        {label:"Passed",value:Number(report.passed)},
        {label:"Net Revenue Gap",value:delta,unit:"THB"}];
      out.checks=[
        {label:"Paid items reconcile",pass:totals.paid_items===Number(report.warehouse_sales_item_count)},
        {label:"Net Revenue reconcile ±0.01 THB",pass:Math.abs(delta)<=0.01},
        {label:"Warehouse validation has no failures",pass:Number(report.failed)===0}
      ];
      out.provenance="LIVE_RECALCULATION_CHECK_NOT_NEW_VALIDATE_BATCH";
    }
    out.success=out.checks.every(c=>c.pass===true);
    return res.status(200).json(out);
  }catch(error){
    console.error("Classroom read-only stage failed",error?.code||error?.name||"unknown");
    return res.status(503).json({
      stage,mode:"READ_ONLY_EVIDENCE_REPLAY",success:false,
      error:"อ่านหลักฐานของ Step นี้ไม่สำเร็จ กรุณาตรวจข้อมูลและพื้นที่เก็บไฟล์ แล้วกด Retry",
      error_type:error?.name||"UNKNOWN",is_new_etl_run:false
    });
  }
}
