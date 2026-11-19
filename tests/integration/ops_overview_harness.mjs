// Data Operations overview against a mock backend that has the exact /api/lab-batch + ?dq=state + ?fc=monitoring shapes. Scenario via argv[3].
import http from "node:http"; import fs from "node:fs"; import path from "node:path"; import { createRequire } from "node:module";
import { readMonitoring } from "/home/user/tiktok-shop-pipeline-demo/lib/lab-mlops.js";
const require = createRequire(import.meta.url); const { chromium } = require("playwright");
const SP = process.env.SP, root = "/home/user/tiktok-shop-pipeline-demo/dashboard", scenario = process.argv[3] || "march";
const CYCLE = Number(fs.readFileSync(`${SP}/ml_pg4/cycle.txt`, "utf8"));
const store = { getJson: async k => { const f = path.join(SP, "ml_pg4", k.replace(/^vercel-lab\//, "")); return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, "utf8")) : null; } };
const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml" };
const D = ["initial", ...Array.from({ length: 9 }, (_, i) => "incremental_0" + (i + 1))];
const mkRuns = n => D.slice(0, n).map((b, i) => ({ run_id: "run-" + (i + 1), batch: b, source_batch: b, source_month: "2026-" + String(i + 1).padStart(2, "0"), run_type: i ? "RUN2" : "RUN1", status: "SUCCEEDED", created_at: `2026-11-1${i}T10:00:00Z`, source_version: "classroom_v2_2026_11_16" }));
const months = (n, over) => D.map((b, i) => ({ batch: b, month: "2026-" + String(i + 1).padStart(2, "0"), state: i < n ? "PUBLISHED" : i === n ? "RUNNABLE" : "LOCKED", reason: i > n ? "PREVIOUS_MONTH_NOT_PUBLISHED" : null, last_stage: null, run_id: i < n ? "run-" + (i + 1) : null, ...(i === n ? over || {} : {}) }));
const issue = { issue_id: "i1", status: "OPEN", table_name: "Fact_Order_Items", column_name: "SKU_ID", source_row_no: 1, rule_id: "REFERENCE_EXISTS:Fact_Order_Items.SKU_ID->Dim_SKU.SKU_ID", source_file: "Fact_Order_Items.csv", pk_json: { Order_Item_ID: "ORD-202603-00001-I1" }, invalid_value: "SKU_ERR_UNKNOWN_DEMO", parent_table: "Dim_SKU", source_file_sha256: "c", source_zip_sha256: "6", current_version: 0, row_snapshot: { SKU_ID: "SKU_ERR_UNKNOWN_DEMO" }, context: {} };
const snap = n => D.slice(0, n).map((b, i) => ({ batch: b, run_id: "run-" + (i + 1), source_version: "classroom_v2_2026_11_16", source_zip_sha256: "6", correction_set_id: null, published_at: `2026-11-1${i}T10:05:00Z`, is_current: i === n - 1 }));
function labBatch() {
  const base = { ready: true, cycle: CYCLE, orders: 9000, running: false, requires_reset: false, execution_engine: "VERCEL_NATIVE", recovery_ready: true, partial_data_detected: false, source_exhausted: false, history: [] };
  if (scenario === "march") return { ...base, phase: "RUN2_READY", current_run_id: "run-2", published_through: "2026-02", published_snapshots: snap(2), next_source_batch: "incremental_02",
    months: months(2, { state: "DATA_QUALITY_BLOCKED", reason: "BLOCKED_DQ", last_stage: "ingest", run_id: "run-b3" }), current_cycle_runs: [...mkRuns(2), { run_id: "run-b3", batch: "incremental_02", source_batch: "incremental_02", source_month: "2026-03", run_type: "RUN2", status: "BLOCKED_DQ", created_at: "2026-11-12T10:00:00Z" }],
    dq_blocked: { run_id: "run-b3", status: "BLOCKED_DQ", batch: "incremental_02", failed_stage: "ingest", issue_count: 1 } };
  if (scenario === "ready") return { ...base, phase: "RUN2_READY", current_run_id: "run-2", published_through: "2026-02", published_snapshots: snap(2), next_source_batch: "incremental_02", months: months(2), current_cycle_runs: mkRuns(2) };
  if (scenario === "fail") return { ...base, phase: "RUN2_READY", current_run_id: "run-2", published_through: "2026-02", published_snapshots: snap(2), next_source_batch: "incremental_02", months: months(2, { state: "SYSTEM_FAILED", reason: "RETRYABLE", last_stage: "load", run_id: "run-f3" }),
    current_cycle_runs: [...mkRuns(2), { run_id: "run-f3", batch: "incremental_02", source_batch: "incremental_02", source_month: "2026-03", run_type: "RUN2", status: "FAILED", created_at: "2026-11-12T10:00:00Z" }], latest_failed_run: { run_id: "run-f3", run_type: "RUN2", failed_stage: "load", error_code: "WAREHOUSE_WRITE_TIMEOUT", batch: "incremental_02" } };
  if (scenario === "empty") return { ...base, phase: "EMPTY", orders: 0, current_run_id: null, next_source_batch: "initial", published_snapshots: [], months: months(0), current_cycle_runs: [] };
  return null;
}
const json = (res, o, c = 200) => { res.statusCode = c; res.setHeader("content-type", "application/json"); res.end(JSON.stringify(o)); };
const server = http.createServer((req, res) => { const u = new URL(req.url, "http://x"); req.resume(); req.on("end", async () => {
  if (u.pathname === "/api/lab-batch") { const b = labBatch(); return b ? json(res, b) : json(res, { error: "down" }, 503); }
  if (u.searchParams.get("dq") === "state") return json(res, scenario === "march" ? { ok: true, blocked: true, run: { run_id: "run-b3", status: "BLOCKED_DQ", batch: "incremental_02", failed_stage: "ingest" }, issues: [issue], rule_summary: { rules: 92, failed: 1, checked_rows: 100, failed_rows: 1 }, latest_revalidation: null, revalidated: false, ready_to_resume: false, correction_set_id: null } : { ok: true, blocked: false });
  if (u.pathname === "/api/lab-batch-result" && u.searchParams.get("fc") === "monitoring") return scenario === "ready" || scenario === "march" ? json(res, { ok: true, ...(await readMonitoring(CYCLE, "2026-10", { mlopsStorage: store })), gaps: [] }) : json(res, { error: "MLOPS_STORAGE_UNAVAILABLE" }, 503);
  if (u.pathname.startsWith("/api/")) return json(res, {}, 503);
  const f = path.join(root, u.pathname === "/" ? "index.html" : u.pathname); if (!fs.existsSync(f)) { res.statusCode = 404; return res.end(); }
  res.setHeader("content-type", mime[path.extname(f)] || "application/octet-stream"); res.end(fs.readFileSync(f)); }); }).listen(0, async () => {
  const port = server.address().port, out = process.argv[2]; const b = await chromium.launch(); const errs = [];
  for (const [tag, vp] of [["desktop", { width: 1440, height: 1100 }], ["mobile", { width: 390, height: 900 }]]) {
    const pg = await b.newPage({ viewport: vp }); pg.on("pageerror", e => errs.push(e.message));
    await pg.goto(`http://localhost:${port}/`); await pg.waitForSelector("[data-view=pipeline]"); await pg.click("[data-view=pipeline]"); await pg.waitForSelector(".ops-overview", { timeout: 8000 }); await pg.waitForTimeout(900);
    const t = (await pg.locator(".ops-overview").innerText()).replace(/\n+/g, " | ");
    if (!(await pg.locator(".ops-section").count())) { console.log(`[${scenario}] ${tag}: no sections; text =`, t.slice(0, 220)); await pg.screenshot({ path: `${out}/ops_${scenario}_${tag}.png`, fullPage: true }); await pg.close(); continue; }
    if (tag === "desktop") { console.log(`[${scenario}] cards:`, (await pg.locator(".ops-top, .ops-chips, .ops-stagebox").allInnerTexts()).map(x => x.replace(/\n+/g, " / ")).join(" || "));
      console.log(`[${scenario}] action:`, (await pg.locator(".ops-action").allInnerTexts()).join(" ").replace(/\n+/g, " "));
      await pg.locator(".ops-section").first().evaluate(e => { e.open = true; }); console.log(`[${scenario}] month rows:`, (await pg.locator(".ops-section").first().locator("tbody tr").allInnerTexts()).map(x => x.replace(/\s+/g, " ")).join(" ¦ ").slice(0, 900));
      console.log(`[${scenario}] ML:`, (await pg.locator(".ops-section").last().evaluate(e => { e.open = true; return e.innerText; })).replace(/\n+/g, " | ").slice(0, 420));
      console.log(`[${scenario}] mobile-scroll-safe(desktop)`, await pg.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      if (scenario === "march") { await pg.click(".ops-action button:has-text('Review & Fix')"); await pg.waitForSelector(".review-fix-drawer", { timeout: 4000 }); console.log("[march] click 'ไปที่ Review & Fix' opens drawer: true");
        await pg.reload(); await pg.click("[data-view=pipeline]"); await pg.waitForSelector(".ops-overview"); await pg.waitForTimeout(700); console.log("[march] after refresh cards:", (await pg.locator(".ops-top, .ops-chips, .ops-stagebox").allInnerTexts()).map(x => x.replace(/\n+/g, " / ")).join(" || ")); }
      console.log(`[${scenario}] runner controls still present:`, await pg.locator("button:has-text('รันเดือนนี้')").count(), "| month chips:", await pg.locator(".month-chip").count(), "| stages:", await pg.locator(".notebook-cell, .notebook-stage").count()); }
    else console.log(`[${scenario}] mobile overflow (page scrollWidth vs viewport):`, await pg.evaluate(() => document.documentElement.scrollWidth + " / " + innerWidth), "| ops-overview scrollWidth:", await pg.evaluate(() => { const e = document.querySelector(".ops-overview"); return e ? e.scrollWidth + "/" + e.clientWidth : "none"; }), "| widest offenders:", await pg.evaluate(() => [...document.querySelectorAll("body *")].filter(e => e.getBoundingClientRect().right > innerWidth + 1).slice(0, 4).map(e => e.className.toString().slice(0, 40)).join(",")));
    await pg.evaluate(() => document.querySelectorAll(".ops-section").forEach(e => { e.open = e.dataset.k === "x"; })); await pg.locator(".ops-overview").screenshot({ path: `${out}/ops_${scenario}_${tag}_compact.png` }); await pg.screenshot({ path: `${out}/ops_${scenario}_${tag}.png`, fullPage: true }); await pg.close(); }
  console.log(`[${scenario}] page errors:`, JSON.stringify(errs.filter(e => !/503/.test(e)))); await b.close(); server.close(); });
