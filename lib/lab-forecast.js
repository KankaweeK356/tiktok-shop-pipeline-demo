/** Forecast, planning, scenario and evaluation API. Mounted at `/api/lab-batch-result?fc=<operation>`
 *  (no new Vercel Function). State-changing operations are single atomic SQL statements or signed
 *  worker tickets; the browser never writes the database.
 *
 *  GET  fc=status | target&month= | forecast&month= | evaluation&month= | evaluations
 *  POST fc=generate | seal | simulate | seal_plan
 *  GET  fc=monitoring (Champion-Challenger summary) | fc=mlops&month=   (read-only MLOps evidence)   POST fc=mlops_run (signed worker ticket for a historical/experiment ML run)
 */
import { createHmac, randomUUID } from "node:crypto";
import planning from "../dashboard/data/planning_targets_v1.json" with { type: "json" };
import { simulate, CALCULATOR_VERSION } from "./scenario-calc.js";
import { buildReferencePlan } from "./scenario-reference.js";
import { getNeonSql } from "./neon-router.js";
import { sameOrigin } from "./lab-dq.js";
import { ML_PREFIX, monitoringStream, defaultMlopsStorage } from "./lab-mlops.js";
import { DELIVERIES } from "./deliveries.js";
import { readMlops, readMonitoring, readShadow } from "./lab-mlops.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MONTH = /^2026-(0[1-9]|1[0-2])$/;
export const GROUPS = ["PG01", "PG02", "PG03", "PG04", "PG05"];
export const FORECAST_GATE_FROM = "2026-06";
export const MAX_DRAFTS_PER_MONTH = 5;      // repeated "generate" calls cannot create unlimited drafts
export const MAX_SIM_BASKETS = 5000, MAX_SIM_LINES = 50;   // bounds the CPU a public caller can spend in "simulate"
export const MIN_HISTORY_MONTHS = 5;       // an OFFICIAL forecast needs at least five consecutive PUBLISHED months (Jan-May for June)

const batchFor = month => DELIVERIES[Number(month.slice(5)) - 1] || null;
const prevMonth = m => { const d = new Date(Date.UTC(Number(m.slice(0, 4)), Number(m.slice(5)) - 2, 1)); return d.toISOString().slice(0, 7); };
/** POSTs that write or spend resources must carry browser provenance. This is CSRF / casual-abuse protection only, NOT authorization
 *  (a script can forge these headers): real limits come from server-side state checks, signed short-lived tickets, idempotency, caps and the platform rate limit. */
export function strictOrigin(req) {
  const site = String(req.headers?.["sec-fetch-site"] || ""), origin = String(req.headers?.origin || ""), host = String(req.headers?.host || "");
  if (site && !["same-origin", "same-site"].includes(site)) return false;
  if (origin && host) { try { return new URL(origin).host === host; } catch (_e) { return false; } }
  return site === "same-origin";
}
const text = (v, min, max) => { const s = typeof v === "string" ? v.trim() : ""; return s.length >= min && s.length <= max ? s : null; };
const fail = (res, status, code, error, extra = {}) => res.status(status).json({ ok: false, error_code: code, error, ...extra });

/** Official target of a month: pre-configured planning seed only (no Source, no QA files). */
export function targetFor(month) {
  const m = planning.months[month];
  if (!m) return { status: "MISSING_TARGET", month };
  return { status: "OK", month, ...m, policy_version: planning.policy_version, label: planning.label,
           source_sha256: planning.source_sha256, classification: planning.classification };
}

/** Pure evaluation of ONE sealed forecast against the published actual of the same month. */
export function evaluateForecast(predicted, actual) {
  const groups = GROUPS.map(g => {
    const f = Number(predicted[g]), a = Number(actual[g]);
    const error = a - f;                                   // signed: Actual - Forecast
    return { group: g, forecast: f, actual: a, error: round2(error), abs_error: round2(Math.abs(error)),
             ape_pct: a > 0 ? round2(100 * Math.abs(error) / a) : null };
  });
  const forecast = groups.reduce((s, x) => s + x.forecast, 0), act = groups.reduce((s, x) => s + x.actual, 0);
  const absSum = groups.reduce((s, x) => s + x.abs_error, 0);
  return { groups, shop: { forecast: round2(forecast), actual: round2(act), error: round2(act - forecast),
      abs_error: round2(Math.abs(act - forecast)), ape_pct: act > 0 ? round2(100 * Math.abs(act - forecast) / act) : null },
    group_wape_pct: act > 0 ? round2(100 * absSum / act) : null, group_mae: round2(absSum / GROUPS.length) };
}
const round2 = v => Math.round(v * 100) / 100;

/** Aggregate WAPE over many months: sum|error| / sum(actual) (never an average of APEs). */
export function aggregateEvaluations(items) {
  const act = items.reduce((s, x) => s + x.shop.actual, 0);
  const shopAbs = items.reduce((s, x) => s + x.shop.abs_error, 0);
  const groupAbs = items.reduce((s, x) => s + x.groups.reduce((a, g) => a + g.abs_error, 0), 0);
  return { months: items.length, shop_wape_pct: act > 0 ? round2(100 * shopAbs / act) : null,
           group_wape_pct: act > 0 ? round2(100 * groupAbs / act) : null,
           shop_mae: items.length ? round2(shopAbs / items.length) : null,
           shop_bias: items.length ? round2(items.reduce((s, x) => s + (x.shop.forecast - x.shop.actual), 0) / items.length) : null };
}

async function readBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  const chunks = []; let bytes = 0;
  for await (const c of req) { bytes += c.length; if (bytes > 262144) throw Error("too large"); chunks.push(c); }
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

async function defaultReadBatchSummary(runId) {
  const { S3Client, GetObjectCommand } = await import("@aws-sdk/client-s3");
  const s3 = new S3Client({ region: process.env.CLASSROOM_STORAGE_REGION || "auto", endpoint: process.env.CLASSROOM_STORAGE_ENDPOINT,
    forcePathStyle: true, credentials: { accessKeyId: process.env.CLASSROOM_STORAGE_KEY_ID, secretAccessKey: process.env.CLASSROOM_STORAGE_SECRET } });
  const obj = await s3.send(new GetObjectCommand({ Bucket: process.env.CLASSROOM_STORAGE_BUCKET, Key: `vercel-lab/results/${runId}/batch.json` }));
  return JSON.parse(Buffer.from(await obj.Body.transformToByteArray()).toString("utf8"));
}

async function cycleState(sql) {
  const s = (await sql.query("SELECT phase,cycle_number,last_run_id::text AS last_run_id FROM demo_control.dataset_state WHERE dataset_key='classroom'"))[0];
  if (!s) return null;
  const runs = await sql.query(`SELECT run_id::text AS run_id,status,result_summary->>'batch' AS batch FROM demo_control.pipeline_runs
     WHERE dataset_key='classroom' AND cycle_number=$1 AND status<>'CANCELLED' ORDER BY started_at DESC`, [s.cycle_number]);
  const published = DELIVERIES.filter(b => runs.some(r => r.batch === b && r.status === "SUCCEEDED"));
  const through = published.length ? `2026-${String(DELIVERIES.indexOf(published[published.length - 1]) + 1).padStart(2, "0")}` : null;
  // consecutive PUBLISHED months counted from the first delivery, read from the warehouse runs (never from the number of clicks)
  let consecutive = 0;
  while (consecutive < DELIVERIES.length && runs.some(r => r.batch === DELIVERIES[consecutive] && r.status === "SUCCEEDED")) consecutive += 1;
  return { cycle: Number(s.cycle_number), phase: s.phase, last_run_id: s.last_run_id, runs, published_through: through, published_months: consecutive };
}

const FORECAST_COLUMNS = `forecast_run_id::text AS forecast_run_id, to_char(target_month,'YYYY-MM') AS target_month,
  to_char(training_cutoff_date,'YYYY-MM-DD') AS training_cutoff_date, source_warehouse_run_id::text AS source_warehouse_run_id,
  source_snapshot_sha256, method_type, model_name, model_version, feature_version, baseline_validation_wape_pct,
  model_validation_wape_pct, validation_notes, selection_reason, generated_at, sealed_at, status, is_official, created_by`;

async function forecastsFor(sql, cycle, month) {
  const rows = await sql.query(`SELECT ${FORECAST_COLUMNS} FROM demo_ml.forecast_run WHERE dataset_key='classroom' AND cycle_number=$1
     AND target_month=$2::date ORDER BY is_official DESC, generated_at DESC`, [cycle, month + "-01"]);
  for (const f of rows) {
    const res = await sql.query("SELECT product_group_id,predicted_net_revenue::float AS predicted FROM demo_ml.forecast_result WHERE forecast_run_id=$1::uuid ORDER BY 1", [f.forecast_run_id]);
    f.results = Object.fromEntries(res.map(r => [r.product_group_id, r.predicted]));
    f.shop_forecast = round2(res.reduce((s, r) => s + r.predicted, 0));
  }
  return rows;
}

export const SEAL_SQL = `
WITH f AS (SELECT * FROM demo_ml.forecast_run WHERE forecast_run_id=$1::uuid AND status='DRAFT' AND dataset_key='classroom' FOR UPDATE),
st AS (SELECT cycle_number,last_run_id FROM demo_control.dataset_state WHERE dataset_key='classroom'),
ok AS (SELECT f.forecast_run_id FROM f, st
        WHERE f.cycle_number=st.cycle_number AND f.source_warehouse_run_id=st.last_run_id
          AND NOT EXISTS (SELECT 1 FROM demo_control.pipeline_runs r WHERE r.dataset_key='classroom' AND r.cycle_number=f.cycle_number
                           AND r.result_summary->>'batch'=$2 AND r.status<>'CANCELLED')
          AND NOT EXISTS (SELECT 1 FROM demo_ml.forecast_run o WHERE o.dataset_key='classroom' AND o.cycle_number=f.cycle_number
                           AND o.target_month=f.target_month AND o.is_official)),
upd AS (UPDATE demo_ml.forecast_run SET status='SEALED', is_official=true, sealed_at=now(),
               validation_notes=COALESCE(validation_notes||' | ','')||'sealed_by:'||$3
         WHERE forecast_run_id IN (SELECT forecast_run_id FROM ok) RETURNING forecast_run_id::text AS forecast_run_id, sealed_at)
SELECT (SELECT COUNT(*) FROM f)::int AS found, (SELECT COUNT(*) FROM ok)::int AS eligible, (SELECT row_to_json(upd) FROM upd) AS sealed`;

function sign(claim) {
  const encoded = Buffer.from(JSON.stringify(claim)).toString("base64url");
  return encoded + "." + createHmac("sha256", process.env.CLASSROOM_LAB_ADMIN_KEY).update(encoded).digest("hex");
}

async function status(sql, res) {
  const st = await cycleState(sql);
  if (!st) return fail(res, 503, "NO_STATE", "ไม่พบสถานะ Lab");
  const months = [];
  for (let i = 1; i < 10; i++) {
    const month = `2026-${String(i + 1).padStart(2, "0")}`;
    const f = await forecastsFor(sql, st.cycle, month);
    const official = f.find(x => x.is_official) || null;
    const ingested = st.runs.some(r => r.batch === batchFor(month));
    const nextInLine = st.published_through === prevMonth(month);
    const history = st.published_months >= MIN_HISTORY_MONTHS;
    const eligible = nextInLine && history && !ingested;
    months.push({ month, target: targetFor(month), official_forecast_id: official?.forecast_run_id || null, published: st.runs.some(r => r.batch === batchFor(month) && r.status === "SUCCEEDED"),
      draft_count: f.filter(x => !x.is_official).length, can_generate: eligible && !official,
      can_seal: eligible && !official && f.some(x => x.status === "DRAFT"),
      reason: official ? "SEALED" : ingested ? "TARGET_ALREADY_INGESTED" : !nextInLine ? `PUBLISHED_THROUGH_${st.published_through || "NONE"}` : !history ? "INSUFFICIENT_HISTORY" : "READY" });
  }
  return res.status(200).json({ ok: true, cycle: st.cycle, published_through: st.published_through, forecast_gate_from: FORECAST_GATE_FROM, months,
    readiness: { published_months: st.published_months, required_months: MIN_HISTORY_MONTHS, ready: st.published_months >= MIN_HISTORY_MONTHS,
      note: "ครบ 5 เดือนคือเกณฑ์เริ่ม Forecast ของ Demo ไม่ได้หมายความว่า ML ผ่านเกณฑ์ความแม่นยำ" },
    planning: { policy_version: planning.policy_version, label: planning.label, source_sha256: planning.source_sha256 } });
}

async function generate(sql, req, res) {
  const body = await readBody(req); const month = String(body.month || ""); const actor = text(body.actor, 1, 120);
  if (!MONTH.test(month) || !actor) return fail(res, 400, "FIELDS_REQUIRED", "ต้องระบุเดือนเป้าหมายและผู้สั่ง");
  if (!process.env.CLASSROOM_LAB_ADMIN_KEY) return fail(res, 503, "NOT_CONFIGURED", "ยังตั้งค่า Lab ไม่ครบ");
  const st = await cycleState(sql);
  if (st.published_through !== prevMonth(month)) return fail(res, 409, "CUTOFF_NOT_PUBLISHED", `ต้อง Publish ถึง ${prevMonth(month)} ก่อน (ตอนนี้ถึง ${st.published_through || "ยังไม่มี"})`);
  if (st.published_months < MIN_HISTORY_MONTHS) return fail(res, 409, "INSUFFICIENT_HISTORY",
    `ต้อง Publish ครบอย่างน้อย ${MIN_HISTORY_MONTHS} เดือนต่อเนื่องก่อนสร้าง Official Forecast (ตอนนี้ ${st.published_months}/${MIN_HISTORY_MONTHS})`, { published_months: st.published_months, required_months: MIN_HISTORY_MONTHS });
  if (st.runs.some(r => r.batch === batchFor(month))) return fail(res, 409, "TARGET_ALREADY_INGESTED", "เดือนเป้าหมายเริ่มนำเข้าแล้ว ไม่สามารถสร้าง Forecast ทางการได้");
  const all = await forecastsFor(sql, st.cycle, month), official = all.find(f => f.is_official);
  if (official) return fail(res, 409, "ALREADY_SEALED", "เดือนนี้มี Official Forecast ที่ Seal แล้ว");
  if (all.filter(f => !f.is_official).length >= MAX_DRAFTS_PER_MONTH) return fail(res, 429, "DRAFT_LIMIT", `สร้าง Draft ได้ไม่เกิน ${MAX_DRAFTS_PER_MONTH} ครั้งต่อเดือน`);
  const claim = { action: "forecast", target_month: month, cycle: st.cycle, previous_run_id: st.last_run_id, actor,
                  nonce: randomUUID(), expires_at: Date.now() + 10 * 60 * 1000 };
  return res.status(202).json({ ok: true, accepted: true, ticket: sign(claim), month });
}

/** Published months with a sealed official forecast whose evaluation or summary object is missing (read-only). */
async function monitoringGaps(sql, st, store) {
  const stream = monitoringStream(st.cycle), gaps = [];
  for (let i = 0; i < DELIVERIES.length; i++) {
    const month = `2026-${String(i + 1).padStart(2, "0")}`;
    if (month < FORECAST_GATE_FROM || !st.runs.some(r => r.batch === DELIVERIES[i] && r.status === "SUCCEEDED")) continue;
    if (!(await forecastsFor(sql, st.cycle, month)).some(f => f.is_official)) continue;
    const ev = await store.getJson(`${ML_PREFIX}/monitoring/${stream}/evaluations/${month}.json`);
    const sm = ev && await store.getJson(`${ML_PREFIX}/monitoring/${stream}/summary/through=${month}.json`);
    if (!ev || !sm) gaps.push({ month, missing: ev ? "summary" : "evaluation" });
  }
  return gaps;
}

/** Signed ticket for recovery after a temporary monitoring failure. No ticket (and no worker run) unless something is really missing. */
async function monitoringRepair(sql, req, res, deps = {}) {
  if (!process.env.CLASSROOM_LAB_ADMIN_KEY) return fail(res, 503, "NOT_CONFIGURED", "ยังตั้งค่า Lab ไม่ครบ");
  const st = await cycleState(sql); if (!st) return fail(res, 503, "NO_STATE", "ไม่พบสถานะ Lab");
  let gaps;
  try { gaps = await monitoringGaps(sql, st, deps.mlopsStorage || await defaultMlopsStorage()); } catch (_e) { return fail(res, 503, "MLOPS_STORAGE_UNAVAILABLE", "อ่านผล Monitoring ไม่ได้"); }
  if (!gaps.length) return res.status(200).json({ ok: true, accepted: false, nothing_to_repair: true, gaps: [] });
  const claim = { action: "monitoring_repair", cycle: st.cycle, nonce: randomUUID(), expires_at: Date.now() + 10 * 60 * 1000 };
  return res.status(202).json({ ok: true, accepted: true, ticket: sign(claim), gaps });
}

/** Ticket for an ML evidence run that is NOT an official forecast: HISTORICAL_EVALUATION or EXPERIMENT_ONLY. Never creates/changes a forecast. */
async function mlopsRun(sql, req, res, deps = {}) {
  const body = await readBody(req); const month = String(body.month || ""); const actor = text(body.actor, 1, 120);
  const kind = ["HISTORICAL_EVALUATION", "EXPERIMENT_ONLY"].includes(body.kind) ? body.kind : null;
  if (!MONTH.test(month) || !actor || !kind) return fail(res, 400, "FIELDS_REQUIRED", "ต้องระบุเดือนเป้าหมาย ประเภทการรัน และผู้สั่ง");
  if (month < FORECAST_GATE_FROM) return fail(res, 409, "BEFORE_GATE", `ML Evidence เริ่มที่เดือน ${FORECAST_GATE_FROM}`);
  if (!process.env.CLASSROOM_LAB_ADMIN_KEY) return fail(res, 503, "NOT_CONFIGURED", "ยังตั้งค่า Lab ไม่ครบ");
  const st = await cycleState(sql);
  const cutoff = st && prevMonth(month);
  const done = b => st.runs.find(r => r.batch === b && r.status === "SUCCEEDED");
  const cutoffRun = st && done(batchFor(cutoff));
  if (!cutoffRun) return fail(res, 409, "CUTOFF_NOT_PUBLISHED", `ต้อง Publish ถึง ${cutoff} ก่อน (ตอนนี้ถึง ${st?.published_through || "ยังไม่มี"})`);
  if (st.published_months < MIN_HISTORY_MONTHS) return fail(res, 409, "INSUFFICIENT_HISTORY", `ต้อง Publish ต่อเนื่องอย่างน้อย ${MIN_HISTORY_MONTHS} เดือน`);
  const actualRun = kind === "HISTORICAL_EVALUATION" ? done(batchFor(month)) : null;      // post-hoc evaluation only when the target month is already published
  const requestKey = `${ML_PREFIX}/requests/${kind}/${month}/${cutoffRun.run_id}-${actualRun?.run_id || "none"}.json`;
  let existing;
  try { existing = await (deps.mlopsStorage || await defaultMlopsStorage()).getJson(requestKey); }
  catch (_e) { return fail(res, 503, "MLOPS_STORAGE_UNAVAILABLE", "ตรวจคำขอเดิมไม่ได้ จึงยังไม่สร้างคำขอใหม่"); }        // fail closed: cannot prove it is not a repeat
  if (existing) return res.status(200).json({ ok: true, accepted: false, already_recorded: true, month, kind, training_run_id: existing.training_run_id });
  const claim = { action: "mlops", kind, target_month: month, cycle: st.cycle, cutoff_run_id: cutoffRun.run_id, actual_run_id: actualRun?.run_id || null, actor,
                  nonce: randomUUID(), expires_at: Date.now() + 10 * 60 * 1000 };
  return res.status(202).json({ ok: true, accepted: true, ticket: sign(claim), month, kind, post_hoc_actual: Boolean(actualRun) });
}

async function seal(sql, req, res) {
  const body = await readBody(req); const id = String(body.forecast_run_id || ""); const actor = text(body.actor, 1, 120);
  if (!UUID.test(id) || !actor) return fail(res, 400, "FIELDS_REQUIRED", "ต้องระบุ Forecast ID และผู้ Seal");
  const draft = (await sql.query("SELECT to_char(target_month,'YYYY-MM') AS month, status FROM demo_ml.forecast_run WHERE forecast_run_id=$1::uuid", [id]))[0];
  if (!draft) return fail(res, 404, "NOT_FOUND", "ไม่พบ Forecast");
  if (draft.status === "SEALED") return fail(res, 409, "ALREADY_SEALED", "Forecast นี้ Seal แล้ว (แก้ไขไม่ได้)");
  const stNow = await cycleState(sql);
  if (stNow && stNow.published_months < MIN_HISTORY_MONTHS) return fail(res, 409, "INSUFFICIENT_HISTORY",
    `Seal ไม่ได้: ต้อง Publish ครบอย่างน้อย ${MIN_HISTORY_MONTHS} เดือนต่อเนื่อง (ตอนนี้ ${stNow.published_months}/${MIN_HISTORY_MONTHS})`);
  let r;
  try { r = (await sql.query(SEAL_SQL, [id, batchFor(draft.month), actor]))[0]; }
  catch (e) { return fail(res, 409, "SEAL_REJECTED", String(e.message).includes("FIVE_GROUPS") ? "Forecast ต้องมี 5 กลุ่ม PG01–PG05" : "Seal ไม่ผ่านเงื่อนไขของฐานข้อมูล"); }
  if (!r?.sealed) return fail(res, 409, "SEAL_NOT_ALLOWED",
    "Seal ไม่ได้: ต้องเป็น Draft ของ Warehouse ที่ Publish ล่าสุด, เดือนเป้าหมายยังไม่เริ่มนำเข้า และยังไม่มี Official ของเดือนนี้");
  return res.status(200).json({ ok: true, forecast_run_id: id, month: draft.month, sealed_at: r.sealed.sealed_at, status: "SEALED" });
}

async function getForecast(sql, req, res) {
  const month = String(req.query?.month || "");
  if (!MONTH.test(month)) return fail(res, 400, "MONTH_INVALID", "เดือนไม่ถูกต้อง");
  const st = await cycleState(sql);
  const all = await forecastsFor(sql, st.cycle, month);
  const plans = await sql.query(`SELECT scenario_decision_id::text AS id, decision_version, plan_code, plan_title, decision_reason, selected_by, selected_at,
      approved_target_amount::float AS approved_target_amount, target_policy_reference, controls_json, assumptions_json, calculated_result_json, calculator_version
      FROM demo_ml.scenario_decision WHERE dataset_key='classroom' AND cycle_number=$1 AND target_month=$2::date ORDER BY decision_version`, [st.cycle, month + "-01"]);
  return res.status(200).json({ ok: true, month, target: targetFor(month), official: all.find(f => f.is_official) || null,
    drafts: all.filter(f => !f.is_official), selected_plan: plans[plans.length - 1] || null, plan_versions: plans.length,
    plan_status: plans.length ? "SELECTED" : "NO_SELECTED_PLAN" });
}

async function simulateOp(sql, req, res) {
  const body = await readBody(req); const month = String(body.month || "");
  if (!MONTH.test(month)) return fail(res, 400, "MONTH_INVALID", "เดือนไม่ถูกต้อง");
  const t = targetFor(month);
  const baskets = Array.isArray(body.baskets) ? body.baskets : [];
  if (baskets.length > MAX_SIM_BASKETS || baskets.some(b => !b || !Array.isArray(b.lines) || b.lines.length > MAX_SIM_LINES)) return fail(res, 413, "SIMULATION_TOO_LARGE", "ข้อมูลจำลองใหญ่เกินกำหนด");
  try {
    const result = simulate({ month, baskets: body.baskets || [], controls: body.controls || {}, assumptions: body.assumptions || {},
      target: t.status === "OK" ? t : null });
    return res.status(200).json({ ok: true, target: t, result, persisted: false });
  } catch (e) { return fail(res, 400, "SCENARIO_INPUT_INVALID", "ข้อมูลสมมติฐานไม่ถูกต้อง: " + e.message); }
}

async function sealPlan(sql, req, res, deps = {}) {
  const body = await readBody(req); const month = String(body.month || "");
  const actor = text(body.actor, 1, 120), reason = text(body.reason, 10, 2000), title = text(body.plan_title, 1, 200);
  const code = ["A", "B", "C", "CUSTOM"].includes(body.plan_code) ? body.plan_code : null;
  if (!MONTH.test(month) || !actor || !reason || !title || !code) return fail(res, 400, "FIELDS_REQUIRED", "ต้องระบุเดือน แผน ผู้เลือก และเหตุผล (อย่างน้อย 10 ตัวอักษร)");
  const t = targetFor(month);
  if (t.status !== "OK") return fail(res, 409, "MISSING_TARGET", "ไม่มีเป้าหมายที่ตั้งไว้ล่วงหน้าของเดือนนี้");
  const st = await cycleState(sql);
  if (st.runs.some(r => r.batch === batchFor(month))) return fail(res, 409, "TARGET_ALREADY_INGESTED", "เดือนเป้าหมายเริ่มนำเข้าแล้ว ไม่รับแผนหรือการแก้ไขแผนอีก");
  const official = (await forecastsFor(sql, st.cycle, month)).find(f => f.is_official);
  if (!official) return fail(res, 409, "NO_OFFICIAL_FORECAST", "ต้อง Seal Official Forecast ก่อนจึงจะบันทึกแผนได้");
  // The server rebuilds the reference baskets and cost assumptions itself; only the user's CONTROLS come from the browser.
  const ref = await scenarioDefaults(sql, month, deps);
  if (ref.status !== "OK") return fail(res, 409, "REFERENCE_UNAVAILABLE", "สร้างแผนอ้างอิงไม่ได้: " + ref.status);
  body.baskets = ref.baskets; body.assumptions = ref.assumptions;
  let result;
  try { result = simulate({ month, baskets: body.baskets || [], controls: body.controls || {}, assumptions: body.assumptions || {}, target: t }); }
  catch (e) { return fail(res, 400, "SCENARIO_INPUT_INVALID", e.message); }     // the server recomputes: the client result is never trusted
  const rows = await sql.query(`
    WITH prev AS (SELECT scenario_decision_id, decision_version FROM demo_ml.scenario_decision
                   WHERE dataset_key='classroom' AND cycle_number=$1 AND target_month=$2::date ORDER BY decision_version DESC LIMIT 1)
    INSERT INTO demo_ml.scenario_decision
      (scenario_decision_id,dataset_key,cycle_number,target_month,decision_version,supersedes_decision_id,forecast_run_id,source_warehouse_run_id,
       approved_target_amount,target_policy_reference,target_policy_sha256,plan_code,plan_title,decision_reason,selected_by,controls_json,assumptions_json,
       calculated_result_json,calculator_version)
    SELECT gen_random_uuid(),'classroom',$1,$2::date,COALESCE((SELECT decision_version FROM prev),0)+1,(SELECT scenario_decision_id FROM prev),
           $3::uuid,$4::uuid,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13::jsonb,$14::jsonb,$15
    RETURNING scenario_decision_id::text AS id, decision_version`,
    [st.cycle, month + "-01", official.forecast_run_id, official.source_warehouse_run_id, t.revenue_target_thb,
     `${t.policy_version} (${t.label})`, t.source_sha256, code, title, reason, actor, JSON.stringify(body.controls || {}),
     JSON.stringify({ ...(body.assumptions || {}), baskets: body.baskets || [], basket_hash: ref.basket_hash, basis: ref.basis, reference_controls: ref.controls, evidence_of_execution: "NOT_VERIFIED" }), JSON.stringify(result), CALCULATOR_VERSION]);
  return res.status(201).json({ ok: true, scenario_decision_id: rows[0].id, decision_version: rows[0].decision_version, result });
}

/** Reference plan for a scenario: derived ONLY from the previous month's published actuals (ER1 orders that reconcile to the
 *  Published ER2 summary), the Master/rule tables and the sealed Official Forecast. Labelled assumptions, never predictions. */
async function scenarioDefaults(sql, month, deps) {
  const st = await cycleState(sql);
  const official = (await forecastsFor(sql, st.cycle, month)).find(f => f.is_official);
  if (!official) return { status: "NO_OFFICIAL_FORECAST", month };
  const prior = prevMonth(month);
  const run = st.runs.find(r => r.batch === batchFor(prior) && r.status === "SUCCEEDED");
  if (!run) return { status: "PRIOR_MONTH_NOT_PUBLISHED", month };
  const summary = await (deps.readBatchSummary || defaultReadBatchSummary)(run.run_id);
  const shop = (summary.business?.shop_months || []).find(m => m.month === prior);
  const groupRows = (summary.business?.groups || []).filter(g => g.month === prior);
  if (!shop || groupRows.length !== 5) return { status: "PRIOR_MONTH_INCOMPLETE", month };
  const start = prior + "-01", target = month + "-01";
  const items = await sql.query(`SELECT o."Order_ID" AS oid, COALESCE(o."Voucher_ID",'') AS voucher_id, s."Product_Group_ID" AS g, i."Quantity"::int AS q,
      i."Base_Unit_Price_At_Sale"::float AS base, i."Unit_Selling_Price"::float AS sell, (i."Creator_ID" IS NOT NULL) AS creator,
      (i."Total_Selling_Amount" - COALESCE(i."Voucher_Allocated_Amount",0))::float AS net
    FROM demo_er1."Fact_Orders" o JOIN demo_er1."Fact_Order_Items" i ON i."Order_ID"=o."Order_ID" JOIN demo_er1."Dim_SKU" s ON s."SKU_ID"=i."SKU_ID"
    WHERE o."Paid_At" >= $1::date AND o."Paid_At" < ($1::date + interval '1 month') ORDER BY o."Order_ID", i."Order_Item_ID"`, [start]);
  const ruleRows = await sql.query(`SELECT DISTINCT ON ("Product_Group_ID") "Product_Group_ID" AS g, "Affiliate_Commission_Rate"::float AS rate FROM demo_er1."Ref_Affiliate_Commission_Rule"
    WHERE COALESCE("Is_Active", true) AND "Effective_From" <= ($1::date + interval '1 month' - interval '1 day') AND ("Effective_To" IS NULL OR "Effective_To" >= $1::date)
    ORDER BY "Product_Group_ID", "Effective_From" DESC`, [target]);
  const voucherRows = await sql.query(`SELECT v."Voucher_ID" AS id, v."Voucher_Name" AS name, v."Discount_Rate"::float AS rate, v."Minimum_Spend_Amount"::float AS min_spend,
      v."Maximum_Discount_Amount"::float AS cap, (SELECT array_agg(b."Product_Group_ID" ORDER BY b."Product_Group_ID") FROM demo_er1."Bridge_Voucher_Product_Group" b WHERE b."Voucher_ID"=v."Voucher_ID") AS groups
    FROM demo_er1."Dim_Voucher" v WHERE COALESCE(v."Is_Active", true) AND (v."Effective_From" IS NULL OR v."Effective_From" <= ($1::date + interval '1 month' - interval '1 day'))
      AND (v."Effective_To" IS NULL OR v."Effective_To" >= $1::date) ORDER BY v."Voucher_ID"`, [target]);
  const names = Object.fromEntries((await sql.query('SELECT "Product_Group_ID" AS g, "Product_Group_Name" AS n FROM demo_er1."Dim_Product_Group"')).map(r => [r.g, r.n]));
  const ref = buildReferencePlan({ items, rules: Object.fromEntries(ruleRows.map(r => [r.g, r.rate])), vouchers: voucherRows.map(v => ({ ...v, groups: v.groups || [] })),
    groupRows, shop, officialTotal: official.shop_forecast, groupNames: names });
  if (ref.status !== "OK") return { ...ref, month };
  const missingRule = GROUPS.filter(g => ref.groups[g].affiliate.rule_rate === null);
  const orders = ref.basis.reference_orders;
  return { status: "OK", month, ...ref, basis: { ...ref.basis, published_through: prior, source_run_id: run.run_id, forecast_run_id: official.forecast_run_id, missing_affiliate_rules: missingRule,
      note: "ค่าเริ่มต้นคำนวณจากออเดอร์จริงของเดือนก่อนหน้า (Published) และกฎ/Master ที่มีผลในเดือนเป้าหมาย ปริมาณคำสั่งซื้อปรับสเกลให้ใกล้ Official Forecast เป็นสมมติฐานคงที่ ไม่ใช่ผลทำนาย ML และไม่ได้หมายความว่า Ads เพิ่มแล้วยอดขายจะเพิ่ม" },
    assumptions: { cogs_rate_of_base: 0.40, platform_fee_rate_of_net: 0.10, fulfillment_cost_per_order: orders > 0 ? round2(shop.fulfillment / orders) : null,
      free_sample_cost: round2(shop.sample), claim_cost: round2(shop.claim) } };
}

async function evaluation(sql, month, deps) {
  const st = await cycleState(sql);
  const official = (await forecastsFor(sql, st.cycle, month)).find(f => f.is_official);
  if (!official) return { status: "NO_OFFICIAL_FORECAST", month };
  const run = st.runs.find(r => r.batch === batchFor(month) && r.status === "SUCCEEDED");
  if (!run) return { status: "ACTUAL_NOT_PUBLISHED", month, forecast_run_id: official.forecast_run_id };
  const summary = await (deps.readBatchSummary || defaultReadBatchSummary)(run.run_id);
  const rows = (summary.business?.groups || []).filter(g => g.month === month);
  const actual = Object.fromEntries(GROUPS.map(g => [g, Number(rows.find(r => r.group_id === g)?.net ?? 0)]));
  const shop = (summary.business?.shop_months || []).find(m => m.month === month) || null;
  const ev = evaluateForecast(official.results, actual);
  const plans = await sql.query(`SELECT decision_version, plan_code, plan_title, calculated_result_json FROM demo_ml.scenario_decision
      WHERE dataset_key='classroom' AND cycle_number=$1 AND target_month=$2::date ORDER BY decision_version DESC LIMIT 1`, [st.cycle, month + "-01"]);
  let plan = { status: "NO_SELECTED_PLAN" };
  if (plans.length && shop) {
    const p = plans[0].calculated_result_json;
    plan = { status: "SELECTED", version: plans[0].decision_version, plan_code: plans[0].plan_code, evidence_of_execution: "NOT_VERIFIED",
      note: "เทียบตัวเลขตามสมมติฐานของแผนกับผลจริงเท่านั้น ไม่ยืนยันว่ามีการทำตามแผนหรือแผนเป็นสาเหตุของผลลัพธ์",
      variance: { net_revenue: { plan: p.net_revenue, actual: shop.net, diff: round2(shop.net - p.net_revenue) },
                  gross: { plan: p.gross, actual: shop.gross, diff: round2(shop.gross - p.gross) },
                  ads: { plan: p.costs?.ads ?? null, actual: shop.ads, diff: p.costs ? round2(shop.ads - p.costs.ads) : null },
                  profit: { plan: p.contribution_profit, actual: shop.profit, diff: p.contribution_profit === null || shop.profit === null ? null : round2(shop.profit - p.contribution_profit) } } };
  }
  return { status: "OK", month, forecast: { id: official.forecast_run_id, method_type: official.method_type, model_name: official.model_name,
      sealed_at: official.sealed_at, cutoff: official.training_cutoff_date, source_warehouse_run_id: official.source_warehouse_run_id },
    actual_run_id: run.run_id, evaluation: ev, plan };
}

export default async function labForecast(req, res, deps = {}) {
  res.setHeader("Cache-Control", "no-store");
  if (!["GET", "POST"].includes(req.method)) return fail(res, 405, "METHOD", "GET/POST only");
  if (req.method === "POST" && !strictOrigin(req)) return fail(res, 403, "ORIGIN_REQUIRED", "คำขอต้องมาจากหน้าเว็บของระบบนี้เท่านั้น");
  let sql;
  try { sql = deps.sql || getNeonSql("live"); } catch (_e) { return fail(res, 503, "NEON_UNAVAILABLE", "เชื่อมต่อ Neon Lab ไม่ได้"); }
  const op = String(req.query?.fc || "");
  try {
    if (req.method === "GET") {
      if (op === "target") { const m = String(req.query?.month || ""); return MONTH.test(m) ? res.status(200).json({ ok: true, ...targetFor(m) }) : fail(res, 400, "MONTH_INVALID", "เดือนไม่ถูกต้อง"); }
      if (op === "status") return await status(sql, res);
      if (op === "monitoring") { const st = await cycleState(sql); if (!st) return fail(res, 503, "NO_STATE", "ไม่พบสถานะ Lab");
        try { const store = deps.mlopsStorage || await defaultMlopsStorage(); return res.status(200).json({ ok: true, ...(await readMonitoring(st.cycle, st.published_through, { mlopsStorage: store })), gaps: await monitoringGaps(sql, st, store) }); } catch (_e) { return fail(res, 503, "MLOPS_STORAGE_UNAVAILABLE", "อ่านผล Monitoring จาก Object Storage ไม่ได้"); } }
      if (op === "mlops_shadow") { const id = String(req.query?.forecast_id || ""); if (!UUID.test(id)) return fail(res, 400, "FORECAST_ID_INVALID", "Forecast ID ไม่ถูกต้อง");
        try { return res.status(200).json({ ok: true, ...(await readShadow(id, deps)) }); } catch (_e) { return fail(res, 503, "MLOPS_STORAGE_UNAVAILABLE", "อ่าน Shadow Forecast ไม่ได้"); } }
      if (op === "mlops") { const m = String(req.query?.month || ""); if (!MONTH.test(m)) return fail(res, 400, "MONTH_INVALID", "เดือนไม่ถูกต้อง");
        try { return res.status(200).json({ ok: true, ...(await readMlops(m, deps)) }); } catch (_e) { return fail(res, 503, "MLOPS_STORAGE_UNAVAILABLE", "อ่าน ML Artifact จาก Object Storage ไม่ได้"); } }
      if (op === "forecast") return await getForecast(sql, req, res);
      if (op === "evaluation") {
        const m = String(req.query?.month || "");
        return MONTH.test(m) ? res.status(200).json({ ok: true, ...(await evaluation(sql, m, deps)) }) : fail(res, 400, "MONTH_INVALID", "เดือนไม่ถูกต้อง");
      }
      if (op === "defaults") {
        const m = String(req.query?.month || "");
        if (!MONTH.test(m)) return fail(res, 400, "MONTH_INVALID", "เดือนไม่ถูกต้อง");
        return res.status(200).json({ ok: true, ...(await scenarioDefaults(sql, m, deps)) });
      }
      if (op === "evaluations") {
        const out = [];
        for (let i = 1; i < 10; i++) { const m = `2026-${String(i + 1).padStart(2, "0")}`; const e = await evaluation(sql, m, deps); if (e.status === "OK") out.push(e); }
        return res.status(200).json({ ok: true, months: out, aggregate: aggregateEvaluations(out.map(e => e.evaluation)) });
      }
    } else {
      if (op === "generate") return await generate(sql, req, res);
      if (op === "mlops_run") return await mlopsRun(sql, req, res, deps);
      if (op === "monitoring_repair") return await monitoringRepair(sql, req, res, deps);
      if (op === "seal") return await seal(sql, req, res);
      if (op === "simulate") return await simulateOp(sql, req, res);
      if (op === "seal_plan") return await sealPlan(sql, req, res, deps);
    }
    return fail(res, 400, "OPERATION_UNKNOWN", "ไม่รู้จักคำสั่ง fc นี้");
  } catch (error) {
    const missing = /demo_ml|forecast_run|forecast_result|scenario_decision/i.test(String(error?.message || ""));
    return fail(res, missing ? 503 : 500, missing ? "ML_SCHEMA_MISSING" : "FORECAST_API_ERROR",
      missing ? "ยังไม่ได้ติดตั้ง Migration demo_ml บน Neon branch นี้" : "ระบบ Forecast ขัดข้อง");
  }
}
