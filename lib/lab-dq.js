/** Review & Fix API for persisted data-quality issues (Neon `demo_control.dq_*`).
 *
 * Exposed through `/api/lab-batch-result?dq=<operation>` so no new Vercel Function is
 * needed. Every state change is a single SQL statement (atomic). The browser never writes
 * the database directly and never supplies SQL identifiers: the table/column that may be
 * used for a replacement value always comes from the persisted issue and is validated
 * against the Source contract.
 *
 *   GET  dq=state                      current blocked run + issues + latest revalidation
 *   GET  dq=candidates&issue_id=…      rows of the authoritative parent master (e.g. Dim_SKU)
 *   GET  dq=history&issue_id=…         append-only correction ledger of one issue
 *   GET  dq=rules&run_id=…             rule evaluations of a run
 *   POST dq=correct                    append a versioned correction (human decision)
 *   POST dq=revalidate                 signed ticket for the worker to re-run the same rules
 */
import { createHmac, randomUUID } from "node:crypto";
import sourceContract from "../dashboard/data/classroom_source_contract.json" with { type: "json" };
import { getNeonSql } from "./neon-router.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const IDENT = /^[A-Za-z_][A-Za-z0-9_]*$/;
const BLOCKED = ["BLOCKED_DQ", "READY_TO_RESUME"];

const text = (value, min, max) => {
  const v = typeof value === "string" ? value.trim() : "";
  return v.length >= min && v.length <= max ? v : null;
};
function fail(res, status, code, message, extra = {}) {
  return res.status(status).json({ ok: false, error_code: code, error: message, ...extra });
}
/** Same-origin only when the browser sends origin metadata (no cross-site form posts). */
export function sameOrigin(req) {
  const site = String(req.headers?.["sec-fetch-site"] || "");
  if (site && !["same-origin", "same-site", "none"].includes(site)) return false;
  const origin = String(req.headers?.origin || "");
  const host = String(req.headers?.host || "");
  if (origin && host) { try { return new URL(origin).host === host; } catch (_e) { return false; } }
  return true;
}
/** Parent table / column used for validation and candidates: from the issue, never the client. */
export function safeParent(issue) {
  const table = String(issue.parent_table || ""), column = String(issue.parent_column || "");
  if (!IDENT.test(table) || !IDENT.test(column)) return null;
  if (!sourceContract.source_tables.includes(table)) return null;
  if (!(sourceContract.columns[table] || []).includes(column)) return null;
  return { table, column };
}
async function readBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  const chunks = [];
  let bytes = 0;
  for await (const chunk of req) {
    bytes += chunk.length;
    if (bytes > 16384) throw Error("Request body too large");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

const CURRENT_BLOCKED_RUN = `
  SELECT r.run_id::text AS run_id, r.status, r.result_summary, r.cycle_number, r.started_at, r.finished_at
    FROM demo_control.pipeline_runs r
    JOIN demo_control.dataset_state s ON s.dataset_key=r.dataset_key AND s.cycle_number=r.cycle_number
   WHERE r.dataset_key='classroom' AND r.status = ANY($1::text[])
   ORDER BY r.started_at DESC LIMIT 1`;

async function state(sql, res) {
  const runs = await sql.query(CURRENT_BLOCKED_RUN, [BLOCKED]);
  if (!runs.length) return res.status(200).json({ ok: true, blocked: false });
  const run = runs[0];
  const batch = run.result_summary?.batch || null;
  const issues = await sql.query(`
    SELECT i.issue_id::text, i.rule_id, i.severity, i.table_name, i.source_file, i.source_file_sha256,
           i.source_zip_sha256, i.source_row_no, i.pk_json, i.column_name, i.invalid_value,
           i.parent_table, i.parent_column, i.row_snapshot, i.context, i.evidence_uri, i.status,
           i.created_at, i.updated_at,
           COALESCE((SELECT MAX(version) FROM demo_control.dq_correction c WHERE c.issue_id=i.issue_id),0)::int AS current_version,
           (SELECT row_to_json(e) FROM (
              SELECT c.correction_id::text, c.version, c.original_value, c.corrected_value, c.actor,
                     c.reason, c.evidence_ref, c.created_at
                FROM demo_control.dq_correction c WHERE c.issue_id=i.issue_id
               ORDER BY c.version DESC LIMIT 1) e) AS latest_correction
      FROM demo_control.dq_issue i
     WHERE i.dataset_key='classroom' AND i.cycle_number=$1 AND i.batch=$2
     ORDER BY i.table_name, i.source_row_no`, [Number(run.cycle_number), batch]);
  const zip = issues[0]?.source_zip_sha256 || null;
  const [set, reval, rules] = await Promise.all([
    sql.query("SELECT demo_control.dq_correction_set_id('classroom',$1,$2,$3) AS id", [Number(run.cycle_number), batch, zip]),
    sql.query(`SELECT reval_id::text, status, correction_set_id, failed_rules, failed_rows, rules_executed, actor, executed_at
                 FROM demo_control.dq_revalidation
                WHERE dataset_key='classroom' AND cycle_number=$1 AND batch=$2
                ORDER BY executed_at DESC LIMIT 1`, [Number(run.cycle_number), batch]),
    sql.query(`SELECT COUNT(*)::int AS rules, COUNT(*) FILTER (WHERE status='FAIL')::int AS failed,
                      COUNT(*) FILTER (WHERE status='NOT_CHECKED')::int AS not_checked,
                      COALESCE(SUM(checked_rows),0)::bigint AS checked_rows,
                      COALESCE(SUM(failed_rows),0)::bigint AS failed_rows
                 FROM demo_control.dq_rule_result WHERE run_id=$1::uuid`, [run.run_id])
  ]);
  const setId = set[0]?.id || null;
  const last = reval[0] || null;
  return res.status(200).json({
    ok: true, blocked: true,
    run: { run_id: run.run_id, status: run.status, batch, cycle: Number(run.cycle_number),
           failed_stage: run.result_summary?.failed_stage || null,
           issue_count: run.result_summary?.issue_count ?? issues.length,
           source: run.result_summary?.source_identity || null,
           evidence_uri: run.result_summary?.dq_evidence_uri || null },
    issues, rule_summary: rules[0] || null,
    correction_set_id: setId, latest_revalidation: last,
    revalidated: Boolean(last && last.status === "PASS" && last.correction_set_id === setId),
    ready_to_resume: run.status === "READY_TO_RESUME"
  });
}

async function loadIssue(sql, id) {
  const rows = await sql.query(`
    SELECT i.issue_id::text, i.parent_table, i.parent_column, i.row_snapshot, i.invalid_value,
           i.status, i.cycle_number, i.batch, i.source_zip_sha256, i.last_run_id::text
      FROM demo_control.dq_issue i
      JOIN demo_control.dataset_state s ON s.dataset_key=i.dataset_key AND s.cycle_number=i.cycle_number
     WHERE i.issue_id=$1::uuid`, [id]);
  return rows[0] || null;
}

async function candidates(sql, req, res) {
  const id = String(req.query?.issue_id || "");
  if (!UUID.test(id)) return fail(res, 400, "ISSUE_ID_INVALID", "รหัส Issue ไม่ถูกต้อง");
  const issue = await loadIssue(sql, id);
  if (!issue) return fail(res, 404, "ISSUE_NOT_FOUND", "ไม่พบ Issue ใน Cycle ปัจจุบัน");
  const parent = safeParent(issue);
  if (!parent) return fail(res, 422, "NO_MASTER_FOR_RULE", "กฎนี้ไม่มีตารางหลัก (Master) ให้เลือกค่า");
  // Authoritative master rows straight from Neon ER1; identifiers validated above.
  const rows = await sql.query(`SELECT * FROM demo_er1."${parent.table}" ORDER BY "${parent.column}" LIMIT 1000`);
  // Optional, clearly-labelled filter hint (never a selection): product groups whose base price
  // equals the price the order line was sold at. Only meaningful for a SKU master.
  let hint = null;
  const price = issue.row_snapshot?.Base_Unit_Price_At_Sale;
  if (parent.table === "Dim_SKU" && price != null) {
    const groups = await sql.query(
      `SELECT "Product_Group_ID" FROM demo_er1."Dim_Product_Group" WHERE "Base_Selling_Price"=$1::numeric`, [price]);
    hint = { kind: "PRODUCT_GROUP_BY_BASE_PRICE", base_unit_price: price,
             product_group_ids: groups.map(r => r.Product_Group_ID),
             note: "ตัวช่วยกรองรายการเท่านั้น ไม่ใช่คำตอบ ต้องยืนยันจากหลักฐานต้นฉบับ" };
  }
  return res.status(200).json({ ok: true, issue_id: id, master_table: parent.table,
    master_column: parent.column, count: rows.length, candidates: rows, hint });
}

async function history(sql, req, res) {
  const id = String(req.query?.issue_id || "");
  if (!UUID.test(id)) return fail(res, 400, "ISSUE_ID_INVALID", "รหัส Issue ไม่ถูกต้อง");
  const rows = await sql.query(`
    SELECT correction_id::text, version, original_value, corrected_value, actor, reason, evidence_ref,
           supersedes_correction_id::text, created_at
      FROM demo_control.dq_correction WHERE issue_id=$1::uuid ORDER BY version`, [id]);
  return res.status(200).json({ ok: true, issue_id: id, corrections: rows });
}

async function rules(sql, req, res) {
  const id = String(req.query?.run_id || "");
  if (!UUID.test(id)) return fail(res, 400, "RUN_ID_INVALID", "Run ID ไม่ถูกต้อง");
  const rows = await sql.query(`
    SELECT rule_id, rule_name, stage_name, evaluation_kind, input_table, input_column, checked_rows,
           failed_rows, threshold, severity, status, source_file, source_file_sha256, executed_at
      FROM demo_control.dq_rule_result WHERE run_id=$1::uuid ORDER BY status DESC, rule_id`, [id]);
  return res.status(200).json({ ok: true, run_id: id, rules: rows });
}

/** One atomic statement: validate, append the correction, move the issue/run state. */
export const CORRECT_SQL = (table, column) => `
WITH iss AS (
  SELECT i.* FROM demo_control.dq_issue i
    JOIN demo_control.dataset_state s ON s.dataset_key=i.dataset_key AND s.cycle_number=i.cycle_number
    JOIN demo_control.pipeline_runs r ON r.run_id=i.last_run_id
   WHERE i.issue_id=$1::uuid AND r.status IN ('BLOCKED_DQ','READY_TO_RESUME')
     AND i.status IN ('OPEN','CORRECTED','REVALIDATED')
     FOR UPDATE OF i
), cur AS (
  SELECT COALESCE(MAX(version),0)::int AS v FROM demo_control.dq_correction WHERE issue_id=$1::uuid
), master AS (
  SELECT 1 AS ok FROM demo_er1."${table}" WHERE "${column}"=$3 LIMIT 1
), ins AS (
  INSERT INTO demo_control.dq_correction
    (issue_id,version,original_value,corrected_value,actor,reason,evidence_ref,supersedes_correction_id,idempotency_key)
  SELECT iss.issue_id, cur.v+1, iss.invalid_value, $3, $4, $5, $6,
         (SELECT correction_id FROM demo_control.dq_correction WHERE issue_id=$1::uuid AND version=cur.v), $7
    FROM iss, cur WHERE cur.v=$2::int AND EXISTS (SELECT 1 FROM master)
  ON CONFLICT (idempotency_key) DO NOTHING
  RETURNING correction_id, issue_id, version
), upd AS (
  UPDATE demo_control.dq_issue SET status='CORRECTED', updated_at=now()
   WHERE issue_id=$1::uuid AND EXISTS (SELECT 1 FROM ins) RETURNING 1
), run AS (
  UPDATE demo_control.pipeline_runs SET status='BLOCKED_DQ'
   WHERE run_id=(SELECT last_run_id FROM iss) AND status='READY_TO_RESUME' AND EXISTS (SELECT 1 FROM ins) RETURNING 1
)
SELECT (SELECT COUNT(*) FROM iss)::int AS issue_found, (SELECT v FROM cur) AS current_version,
       (SELECT COUNT(*) FROM master)::int AS master_ok,
       (SELECT row_to_json(x) FROM ins x LIMIT 1) AS inserted,
       (SELECT row_to_json(c) FROM (SELECT issue_id::text, version, correction_id::text
                                      FROM demo_control.dq_correction WHERE idempotency_key=$7) c) AS replay`;

async function correct(sql, req, res) {
  let body;
  try { body = await readBody(req); } catch (_e) { return fail(res, 400, "BODY_INVALID", "ข้อมูลคำขอไม่ถูกต้อง"); }
  const id = String(body.issue_id || "");
  const value = text(body.corrected_value, 1, 200);
  const actor = text(body.actor, 1, 120);
  const reason = text(body.reason, 10, 2000);
  const evidence = text(body.evidence_ref, 3, 1000);
  const key = text(body.idempotency_key, 8, 100);
  const expected = Number(body.expected_version);
  if (!UUID.test(id)) return fail(res, 400, "ISSUE_ID_INVALID", "รหัส Issue ไม่ถูกต้อง");
  if (!value || !actor || !reason || !evidence || !key || !Number.isInteger(expected) || expected < 0)
    return fail(res, 400, "FIELDS_REQUIRED",
      "ต้องระบุค่าที่ถูกต้อง ผู้ยืนยัน เหตุผล (อย่างน้อย 10 ตัวอักษร) และหลักฐานอ้างอิง");
  const issue = await loadIssue(sql, id);
  if (!issue) return fail(res, 404, "ISSUE_NOT_FOUND", "ไม่พบ Issue ใน Cycle ปัจจุบัน");
  const parent = safeParent(issue);
  if (!parent) return fail(res, 422, "NO_MASTER_FOR_RULE", "กฎนี้ไม่รองรับการแก้ด้วยการเลือกค่าจากตารางหลัก");
  const rows = await sql.query(CORRECT_SQL(parent.table, parent.column),
    [id, expected, value, actor, reason, evidence, key]);
  const r = rows[0] || {};
  if (r.inserted) return res.status(201).json({ ok: true, replayed: false, issue_id: id,
    version: r.inserted.version, correction_id: r.inserted.correction_id, status: "CORRECTED" });
  if (r.replay) {
    if (r.replay.issue_id === id) return res.status(200).json({ ok: true, replayed: true, issue_id: id,
      version: r.replay.version, correction_id: r.replay.correction_id, status: "CORRECTED" });
    return fail(res, 409, "IDEMPOTENCY_KEY_REUSED", "รหัสป้องกันการส่งซ้ำถูกใช้กับ Issue อื่นแล้ว");
  }
  if (!r.issue_found) return fail(res, 409, "ISSUE_NOT_CORRECTABLE", "Issue นี้ไม่อยู่ในสถานะที่แก้ไขได้");
  if (Number(r.current_version) !== expected)
    return fail(res, 409, "VERSION_CONFLICT", "มีผู้แก้ไข Issue นี้ไปแล้ว กรุณาโหลดข้อมูลใหม่", { current_version: r.current_version });
  if (!r.master_ok)
    return fail(res, 422, "VALUE_NOT_IN_MASTER", `ค่า ${value} ไม่มีใน ${parent.table}.${parent.column}`);
  return fail(res, 409, "CORRECTION_NOT_APPLIED", "ไม่สามารถบันทึกการแก้ไขได้");
}

async function revalidate(sql, req, res) {
  let body;
  try { body = await readBody(req); } catch (_e) { return fail(res, 400, "BODY_INVALID", "ข้อมูลคำขอไม่ถูกต้อง"); }
  const actor = text(body.actor, 1, 120);
  if (!actor) return fail(res, 400, "FIELDS_REQUIRED", "ต้องระบุผู้สั่ง Revalidate");
  if (!process.env.CLASSROOM_LAB_ADMIN_KEY) return fail(res, 503, "NOT_CONFIGURED", "ยังตั้งค่า Lab ไม่ครบ");
  const runs = await sql.query(CURRENT_BLOCKED_RUN, [BLOCKED]);
  if (!runs.length) return fail(res, 409, "NOT_BLOCKED", "ไม่มี Run ที่ถูกหยุดด้วยข้อมูลไม่ผ่านการตรวจ");
  const run = runs[0];
  const batch = run.result_summary?.batch;
  const pending = await sql.query(`
    SELECT COUNT(*) FILTER (WHERE status='OPEN')::int AS open_count, COUNT(*)::int AS total
      FROM demo_control.dq_issue WHERE dataset_key='classroom' AND cycle_number=$1 AND batch=$2
       AND status IN ('OPEN','CORRECTED','REVALIDATED')`, [Number(run.cycle_number), batch]);
  if (!pending[0]?.total) return fail(res, 409, "NO_ISSUES", "ไม่พบ Issue ที่ต้อง Revalidate");
  if (pending[0].open_count) return fail(res, 409, "ISSUES_UNCORRECTED",
    `ยังมี ${pending[0].open_count} Issue ที่ยังไม่ได้บันทึกการแก้ไข`);
  const state = await sql.query("SELECT last_run_id::text AS last_run_id FROM demo_control.dataset_state WHERE dataset_key='classroom'");
  const upload = /classroom-source-uploads\/([0-9a-f-]{36})\.zip$/i.exec(String(run.result_summary?.source_identity?.uri || ""));
  const claim = {
    action: "revalidate", batch, cycle: Number(run.cycle_number),
    previous_run_id: batch === "initial" ? "0" : String(state[0]?.last_run_id || ""),
    source_upload_id: upload ? upload[1] : null, actor,
    nonce: randomUUID(), expires_at: Date.now() + 10 * 60 * 1000
  };
  const encoded = Buffer.from(JSON.stringify(claim)).toString("base64url");
  const signature = createHmac("sha256", process.env.CLASSROOM_LAB_ADMIN_KEY).update(encoded).digest("hex");
  return res.status(202).json({ ok: true, accepted: true, ticket: `${encoded}.${signature}`, batch });
}

export default async function labDQ(req, res, deps = {}) {
  res.setHeader("Cache-Control", "no-store");
  if (!["GET", "POST"].includes(req.method)) return fail(res, 405, "METHOD", "GET/POST only");
  if (req.method === "POST" && !sameOrigin(req)) return fail(res, 403, "CROSS_ORIGIN", "คำขอต้องมาจากหน้าเว็บของระบบนี้เท่านั้น");
  let sql;
  try { sql = deps.sql || getNeonSql("live"); } catch (_e) { return fail(res, 503, "NEON_UNAVAILABLE", "เชื่อมต่อ Neon Lab ไม่ได้"); }
  const op = String(req.query?.dq || "");
  try {
    if (req.method === "GET") {
      if (op === "state") return await state(sql, res);
      if (op === "candidates") return await candidates(sql, req, res);
      if (op === "history") return await history(sql, req, res);
      if (op === "rules") return await rules(sql, req, res);
    } else {
      if (op === "correct") return await correct(sql, req, res);
      if (op === "revalidate") return await revalidate(sql, req, res);
    }
    return fail(res, 400, "OPERATION_UNKNOWN", "ไม่รู้จักคำสั่ง dq นี้");
  } catch (error) {
    const missing = /dq_issue|dq_correction|dq_rule_result|dq_revalidation|dq_effective_correction|published_snapshot/i
      .test(String(error?.message || ""));
    return fail(res, missing ? 503 : 500, missing ? "DQ_SCHEMA_MISSING" : "DQ_API_ERROR",
      missing ? "ยังไม่ได้ติดตั้ง Migration ของระบบ DQ บน Neon branch นี้" : "ระบบ Review & Fix ขัดข้อง");
  }
}
