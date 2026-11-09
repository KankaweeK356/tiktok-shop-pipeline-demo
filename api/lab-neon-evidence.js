/** Read-only, bounded classroom branch explorer. No browser supplied SQL. */
import { neon } from "@neondatabase/serverless";

const schemas = ["demo_er1", "demo_control"];
const safeName = value => /^[A-Za-z][A-Za-z0-9_]*$/.test(value);
const printable = value => typeof value === "bigint" ? String(value) : value;

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "private, no-store");
  res.setHeader("X-Content-Type-Options", "nosniff");
  if (req.method !== "GET") return res.status(405).json({error:"GET only"});
  if (!process.env.CLASSROOM_LAB_NEON_URL)
    return res.status(503).json({error:"Lab database is not configured"});
  try {
    const sql = neon(process.env.CLASSROOM_LAB_NEON_URL);
    const rows = await sql.query(
      "SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema = ANY($1) AND table_type = 'BASE TABLE' ORDER BY table_schema, table_name",
      [schemas]
    );
    const schema = String(req.query?.schema || "demo_er1");
    const table = String(req.query?.table || "");
    if (!table) return res.status(200).json({connected:true,branch:"classroom-live-run-lab",
      database:"tiktok_demo",tables:rows});
    if (schema !== "demo_er1" || !safeName(table) ||
        !rows.some(row => row.table_schema === schema && row.table_name === table))
      return res.status(404).json({error:"Table not found"});
    const quoted = '"' + schema + '"."' + table + '"';
    const [sample, count, columns] = await Promise.all([
      sql.query("SELECT * FROM " + quoted + " LIMIT 5"),
      sql.query("SELECT COUNT(*)::int AS n FROM " + quoted),
      sql.query("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema=$1 AND table_name=$2 ORDER BY ordinal_position",[schema,table])
    ]);
    return res.status(200).json({connected:true,branch:"classroom-live-run-lab",
      database:"tiktok_demo",schema,table,row_count:count[0]?.n??0,columns,
      preview_rows:sample.map(row=>Object.fromEntries(Object.entries(row).map(
        ([key,value])=>[key,printable(value)])))});
  } catch (error) {
    console.error("Classroom Neon read failed",error.code || error.name);
    return res.status(503).json({error:"อ่านข้อมูล Lab ไม่สำเร็จ"});
  }
}

