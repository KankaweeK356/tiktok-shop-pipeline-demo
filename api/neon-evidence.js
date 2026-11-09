/** Read-only evidence endpoint for the classroom demo (preview only).
 * Never accepts SQL from the browser. Values are synthetic, not TikTok data.
 * Authentication for public use must be configured before production release.
 */
import { neon } from "@neondatabase/serverless";

const SCHEMA = "demo_er1";
const MAX_PREVIEW_ROWS = 30;
const safeName = value => /^[A-Za-z][A-Za-z0-9_]*$/.test(value);
const asText = value => typeof value === "bigint" ? String(value) : value;

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "private, no-store");
  res.setHeader("X-Content-Type-Options", "nosniff");
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({error: "อนุญาตให้อ่านข้อมูลเท่านั้น"});
  }
  const connection = process.env.CLASSROOM_NEON_READONLY_URL;
  if (!connection) {
    return res.status(503).json({error: "ยังไม่ได้เชื่อม Neon ในสภาพแวดล้อมนี้",connected: false});
  }
  try {
    const sql = neon(connection);
    const tables = await sql.query(
      "SELECT table_name FROM information_schema.tables WHERE table_schema = $1 AND table_type = 'BASE TABLE' ORDER BY table_name",
      [SCHEMA]
    );
    const names = tables.map(row => row.table_name);
    const rawName = req.query?.table;
    const table = typeof rawName === "string" ? rawName : "";
    if (!table) {
      return res.status(200).json({
        connected: true,
        origin: "NEON_LIVE",
        database: "tiktok_demo",
        branch: "demo-pipeline",
        schema: SCHEMA,
        tables: names,
        table_count: names.length,
        generated_at: new Date().toISOString()
      });
    }
    if (!safeName(table) || !names.includes(table)) {
      return res.status(404).json({error:"ไม่พบตารางในฐานข้อมูลต้นทาง"});
    }
    const n = Number(req.query?.limit ?? 10);
    const limit = Number.isInteger(n) ? Math.min(Math.max(n, 1), MAX_PREVIEW_ROWS) : 10;
    const columns = await sql.query(
      "SELECT column_name, data_type, ordinal_position FROM information_schema.columns WHERE table_schema = $1 AND table_name = $2 ORDER BY ordinal_position",
      [SCHEMA, table]
    );
    const quoted = '"' + SCHEMA + '"."' + table + '"';
    const [sample, counts] = await Promise.all([
      sql.query("SELECT * FROM " + quoted + " LIMIT $1", [limit]),
      sql.query("SELECT COUNT(*)::bigint AS count FROM " + quoted)
    ]);
    return res.status(200).json({
      connected: true, origin: "NEON_LIVE", branch: "demo-pipeline", database:"tiktok_demo",
      schema: SCHEMA, table, columns,
      row_count: Number(counts[0]?.count ?? 0),
      preview_rows: sample.map(row => Object.fromEntries(
        Object.entries(row).map(([key, value]) => [key, asText(value)])
      )),
      preview_limit: limit, generated_at: new Date().toISOString()
    });
  } catch (error) {
    console.error("Neon evidence query failed", error.code || error.name);
    return res.status(503).json({
      connected:false,
      error:"ไม่สามารถอ่าน Neon ในขณะนี้ กรุณาตรวจ Connection และสิทธิ์ Server"
    });
  }
}
