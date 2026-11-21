// Journey check of Forecast & Planning v5 with a SYNTHETIC backend that runs the REAL calculator and reference builder.
import http from "node:http"; import fs from "node:fs"; import path from "node:path"; import { createRequire } from "node:module";
import { simulate } from "/home/user/tiktok-shop-pipeline-demo/lib/scenario-calc.js";
import { buildReferencePlan } from "/home/user/tiktok-shop-pipeline-demo/lib/scenario-reference.js";
const require = createRequire(import.meta.url); const { chromium } = require("playwright");
const root = "/home/user/tiktok-shop-pipeline-demo/dashboard", G = ["PG01", "PG02", "PG03", "PG04", "PG05"];
const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml" };
const target = { status: "OK", revenue_target_thb: 94000, minimum_profit_protection_rate: 0.1, maximum_marketing_gap_rate: 0.3, label: "SIMULATED_PRECONFIGURED_FOR_CLASSROOM", policy_version: "planning_v1", source_sha256: "x" };
// synthetic prior-month orders (fixture only)
const prices = { PG01: 199, PG02: 219, PG03: 249, PG04: 179, PG05: 289 }; const items = []; let oid = 0;
for (let i = 0; i < 280; i++) { const g = G[i % 5], g2 = G[(i * 3 + 1) % 5], two = i % 4 === 0; oid++;
  const mk = (gg, creator) => { const base = prices[gg], sell = i % 3 === 0 ? +(base * 0.95).toFixed(2) : base; return { oid: "O" + oid, g: gg, q: 1, base, sell, creator, voucher_id: i % 9 === 0 ? "V08" : "", net: sell }; };
  items.push(mk(g, i % 3 !== 0)); if (two) items.push(mk(g2 === g ? G[(i + 2) % 5] : g2, i % 2 === 0)); }
const priorNet = items.reduce((s, x) => s + x.net, 0);
const vouchers = [{ id: "V08", name: "V08", rate: .08, min_spend: 150, cap: 30, groups: G }, { id: "V10", name: "V10", rate: .1, min_spend: 250, cap: 80, groups: ["PG01", "PG02", "PG05"] }, { id: "V15", name: "V15", rate: .15, min_spend: 350, cap: 100, groups: ["PG02", "PG03", "PG04"] }];
const rules = { PG01: .06, PG02: .08, PG03: .10, PG04: .12, PG05: .09 };
const groupRows = G.map((g, i) => ({ group_id: g, group_name: ["คอกลม", "คอวี", "คอเต่า", "Crop", "Oversize"][i], ads_cost: 4000 + i * 700, profit: 2000 + i * 100 }));
const FORECAST = 89967.41, share = [0.24, 0.206, 0.161, 0.142, 0.247];
const results = Object.fromEntries(G.map((g, i) => [g, +(FORECAST * share[i]).toFixed(2)]));
const ref = buildReferencePlan({ items, rules, vouchers, groupRows, shop: { net: priorNet }, officialTotal: FORECAST, groupNames: Object.fromEntries(groupRows.map(r => [r.group_id, r.group_name])) });
const assumptions = { cogs_rate_of_base: .4, platform_fee_rate_of_net: .1, fulfillment_cost_per_order: 12.5, free_sample_cost: 1030.4, claim_cost: 1474 };
const defaults = { status: "OK", month: "2026-06", ...ref, assumptions, basis: { ...ref.basis, note: "ค่าเริ่มต้นจากออเดอร์จริงเดือนก่อน (fixture)" } };
const mode = process.argv[3] || "ready";               // ready | notready | draft
let sealed = mode === "ready", saved = [], simCalls = 0, delayFirst = process.env.DELAY_FIRST === "1";
const published = mode === "notready" ? 3 : 5;
const official = () => ({ forecast_run_id: "fc-1111", method_type: "BASELINE", model_name: "trailing_3_month_mean", selection_reason: "ML ไม่ผ่าน walk-forward จึงใช้ Baseline", results, shop_forecast: FORECAST,
  training_cutoff_date: "2026-05-31", source_warehouse_run_id: "r5", source_snapshot_sha256: "abcdef0123456789", model_version: "m1", feature_version: "f1" });
const json = (res, o, c = 200) => { res.statusCode = c; res.setHeader("content-type", "application/json"); res.end(JSON.stringify(o)); };
const server = http.createServer((req, res) => { const u = new URL(req.url, "http://x"); let body = ""; req.on("data", d => body += d); req.on("end", async () => {
  if (u.pathname === "/api/lab-batch") return json(res, { ready: true, phase: "RUN2_READY", current_run_id: "r5", months: [], published_snapshots: [], current_cycle_runs: [] });
  if (u.pathname === "/api/lab-batch-result" && u.searchParams.get("fc")) {
    const op = u.searchParams.get("fc");
    if (op === "status") return json(res, { ok: true, published_through: `2026-0${published}`, planning: { label: target.label, policy_version: "planning_v1" },
      readiness: { published_months: published, required_months: 5, ready: published >= 5 },
      months: [{ month: "2026-06", reason: published < 5 ? "INSUFFICIENT_HISTORY" : sealed ? "SEALED" : "READY", can_generate: published >= 5 && !sealed, can_seal: !sealed && published >= 5, published: process.env.LOCKED === "1", target }] });
    if (op === "forecast") return json(res, { ok: true, official: sealed ? official() : null, drafts: !sealed && published >= 5 ? [official()] : [], plan_versions: saved.length, selected_plan: saved.at(-1) || null });
    if (op === "defaults") return json(res, { ok: true, ...defaults });
    if (op === "simulate") { simCalls++; const b = JSON.parse(body); const first = simCalls === 1 && delayFirst;
      const out = { ok: true, result: simulate({ month: b.month, baskets: b.baskets, controls: b.controls, assumptions: b.assumptions, target }), persisted: false };
      if (first) await new Promise(r => setTimeout(r, 900)); return json(res, out); }
    if (op === "seal") { sealed = true; return json(res, { ok: true }); }
    if (op === "seal_plan") { const b = JSON.parse(body); if (process.env.PLAN_MODE === "ingested") return json(res, { ok: false, error_code: "TARGET_ALREADY_INGESTED", error: "เดือนเป้าหมายเริ่มนำเข้าแล้ว ไม่รับแผนหรือการแก้ไขแผน" }, 409); saved.push({ plan_title: b.plan_title, code: b.plan_code, controls: b.controls }); return json(res, { ok: true, decision_version: saved.length }, 201); }
  }
  if (u.pathname.startsWith("/api/")) return json(res, {}, 503);
  const f = path.join(root, u.pathname === "/" ? "index.html" : u.pathname);
  if (!fs.existsSync(f)) { res.statusCode = 404; return res.end(); }
  res.setHeader("content-type", mime[path.extname(f)] || "application/octet-stream"); res.end(fs.readFileSync(f)); }); }).listen(0, async () => {
  const port = server.address().port, out = process.argv[2]; const b = await chromium.launch(); const errs = [];
  const pg = await b.newPage({ viewport: { width: 1440, height: 1100 } }); pg.on("pageerror", e => errs.push(e.message));
  await pg.goto(`http://localhost:${port}/`); await pg.waitForSelector("[data-view=forecast]"); await pg.click("[data-view=forecast]");
  await pg.waitForSelector(".fc-topbar", { timeout: 8000 });
  const text = async sel => (await pg.locator(sel).first().innerText()).replace(/\n+/g, " | ");
  const label = async () => (await pg.locator(".fc-stickyactions .fc-save-btn").innerText()).trim();
  console.log(`[${process.env.PLAN_MODE || "ok"}] before: button="${await label()}" | chip="${(await pg.locator(".fc-stickyactions .ops-chip").innerText()).trim()}"`);
  console.log("planning page ML: pointer =", JSON.stringify((await pg.locator(".mlops-pointer").first().innerText().catch(() => "(none)")).replace(/\n+/g, " ")), "| full ML panel on page:", await pg.locator("#mlopsDetails").count(), "| monitoring block:", await pg.locator(".mlops-mon").count(), "| monthLocked notice:", await pg.locator("text=นำเข้าและ Publish แล้ว").count());
  if (process.env.LOCKED === "1") { console.log("LOCKED month: notice =", JSON.stringify((await pg.locator("text=นำเข้าและ Publish แล้ว").first().innerText()).slice(0, 160)), "| save-review button disabled:", await pg.locator(".fc-stickyactions .fc-save-btn").isDisabled()); console.log("errors:", JSON.stringify(errs)); await b.close(); server.close(); return; }
  await pg.click("button:has-text('ตรวจผลก่อนบันทึก')"); await pg.waitForSelector(".fc-reviewform");
  await pg.click("button:has-text('ยืนยันบันทึกแผนที่เลือก')"); await pg.waitForTimeout(500);
  console.log("  no actor -> message:", (await pg.locator(".fc-flash").first().innerText().catch(() => "(none)")).replace(/\n+/g, " "));
  await pg.fill(".fc-actor", "นิว"); await pg.click("button:has-text('ยืนยันบันทึกแผนที่เลือก')"); await pg.waitForTimeout(1200);
  console.log("  flash:", (await pg.locator(".fc-flash").first().innerText().catch(() => "(NONE)")).replace(/\n+/g, " "));
  console.log("  flash kind ok:", await pg.locator(".fc-flash.notice-ok").count(), "| review panel still open:", await pg.locator(".fc-reviewform").count());
  console.log("  after: button=" + JSON.stringify(await label().catch(() => "(gone)")), "| chip=" + JSON.stringify((await pg.locator(".fc-stickyactions .ops-chip").innerText().catch(() => "")).trim()), "| saved plans:", saved.length);
  await pg.screenshot({ path: `${out}/plan_save_${process.env.PLAN_MODE || "ok"}.png`, fullPage: false });
  if (process.env.PLAN_MODE !== "ingested") { await pg.click(".fc-bulk button:has-text('+10%')"); await pg.waitForTimeout(500); }
  console.log("  flash after editing a control (should be gone):", await pg.locator(".fc-flash").count());
  console.log("errors:", JSON.stringify(errs)); await b.close(); server.close(); });
