import test from "node:test";
import assert from "node:assert/strict";
import labForecast, { evaluateForecast, aggregateEvaluations, targetFor } from "../../lib/lab-forecast.js";

const G = ["PG01", "PG02", "PG03", "PG04", "PG05"];
const mk = values => Object.fromEntries(G.map((g, i) => [g, values[i]]));

test("error is signed Actual - Forecast, APE only when Actual > 0, shop is the sum of groups", () => {
  const ev = evaluateForecast(mk([100, 200, 300, 400, 500]), mk([110, 180, 300, 0, 650]));
  assert.deepEqual(ev.groups.map(g => g.error), [10, -20, 0, -400, 150]);
  assert.equal(ev.groups[3].ape_pct, null);                       // zero actual -> N/A, never 0 or infinity
  assert.equal(ev.shop.forecast, 1500); assert.equal(ev.shop.actual, 1240); assert.equal(ev.shop.error, -260);
  assert.equal(ev.group_wape_pct, Math.round(10000 * 580 / 1240) / 100);   // sum|e| / sum(actual)
});

test("aggregate WAPE is sum|error| / sum(actual), not an average of APEs", () => {
  const a = evaluateForecast(mk([100, 100, 100, 100, 100]), mk([200, 200, 200, 200, 200]));   // shop APE 50%
  const b = evaluateForecast(mk([1000, 1000, 1000, 1000, 1000]), mk([1100, 1100, 1100, 1100, 1100])); // ~9.09%
  const agg = aggregateEvaluations([a, b]);
  assert.equal(agg.shop_wape_pct, Math.round(10000 * (500 + 500) / (1000 + 5500)) / 100);
  assert.notEqual(agg.shop_wape_pct, Math.round(((a.shop.ape_pct + b.shop.ape_pct) / 2) * 100) / 100);
});

test("targets come only from the labelled planning seed; unknown months are MISSING_TARGET", () => {
  const t = targetFor("2026-06");
  assert.equal(t.revenue_target_thb, 94000); assert.equal(t.label, "SIMULATED_PRECONFIGURED_FOR_CLASSROOM");
  assert.equal(targetFor("2027-01").status, "MISSING_TARGET");
});

test("mutating operations validate input before touching the database", async () => {
  const calls = [];
  const sql = { query: async (...a) => { calls.push(a); return []; } };
  const run = (method, query, body, headers = {}) => new Promise(resolve => {
    let status = 200, json = null;
    const res = { setHeader() {}, status(c) { status = c; return this; }, json(v) { json = v; resolve({ status, json }); return this; } };
    labForecast({ method, query, body, headers: { host: "app.test", ...headers } }, res, { sql });
  });
  assert.equal((await run("POST", { fc: "generate" }, { month: "2026-06" })).status, 400);       // actor required
  assert.equal((await run("POST", { fc: "seal" }, { forecast_run_id: "nope", actor: "a" })).status, 400);
  assert.equal((await run("POST", { fc: "seal_plan" }, { month: "2026-06", actor: "a" })).status, 400);
  assert.equal((await run("POST", { fc: "seal" }, { forecast_run_id: "x" }, { "sec-fetch-site": "cross-site" })).status, 403);
  assert.equal(calls.length, 0);
});

// ---- Forecast readiness: five consecutive PUBLISHED months (read from the warehouse runs) --------------------------
import { DELIVERIES } from "../../lib/deliveries.js";
const fakeSql = published => ({
  query: async text => {
    if (text.includes("demo_control.dataset_state")) return [{ phase: "RUN2_READY", cycle_number: 7, last_run_id: "11111111-1111-4111-8111-111111111111" }];
    if (text.includes("demo_control.pipeline_runs")) return published.map(i => ({ run_id: "22222222-2222-4222-8222-22222222222" + i, status: "SUCCEEDED", batch: DELIVERIES[i] }));
    return [];
  } });
const call = (sql, method, query, body) => new Promise(resolve => {
  let status = 200, json = null;
  const res = { setHeader() {}, status(c) { status = c; return this; }, json(v) { json = v; resolve({ status, json }); return this; } };
  process.env.CLASSROOM_LAB_ADMIN_KEY = process.env.CLASSROOM_LAB_ADMIN_KEY || "test-key";
  labForecast({ method, query, body, headers: { host: "app.test", origin: "https://app.test" } }, res, { sql });
});

test("S-01: with only 1-4 months published the status shows n/5 and the API refuses to generate, even when called directly", async () => {
  for (const n of [1, 2, 3, 4]) {
    const published = Array.from({ length: n }, (_, i) => i);
    const st = await call(fakeSql(published), "GET", { fc: "status" });
    assert.equal(st.json.readiness.published_months, n); assert.equal(st.json.readiness.ready, false);
    const next = st.json.months.find(m => m.month === `2026-0${n + 1}`);
    assert.equal(next.can_generate, false); assert.equal(next.reason, "INSUFFICIENT_HISTORY");
    const r = await call(fakeSql(published), "POST", { fc: "generate" }, { month: `2026-0${n + 1}`, actor: "tester" });
    assert.equal(r.status, 409); assert.equal(r.json.error_code, "INSUFFICIENT_HISTORY"); assert.equal(r.json.published_months, n);
  }
});

test("S-02: Jan-May published opens June only (the month after the last published one); a gap in the history does not count", async () => {
  const sql = fakeSql([0, 1, 2, 3, 4]);
  const st = await call(sql, "GET", { fc: "status" });
  assert.equal(st.json.readiness.ready, true);
  assert.equal(st.json.months.find(m => m.month === "2026-06").can_generate, true);
  assert.equal(st.json.months.find(m => m.month === "2026-07").can_generate, false);       // not the month after the last published one
  const ok = await call(sql, "POST", { fc: "generate" }, { month: "2026-06", actor: "tester" });
  assert.equal(ok.status, 202); assert.ok(ok.json.ticket);
  const skip = await call(sql, "POST", { fc: "generate" }, { month: "2026-07", actor: "tester" });
  assert.equal(skip.status, 409); assert.equal(skip.json.error_code, "CUTOFF_NOT_PUBLISHED");
  const gap = await call(fakeSql([0, 1, 3, 4, 5]), "GET", { fc: "status" });               // Mar missing -> only 2 consecutive months
  assert.equal(gap.json.readiness.published_months, 2); assert.equal(gap.json.readiness.ready, false);
});

// ---- MLOps evidence API (reads REAL artifacts generated from the Final source; no network) ----------------------------
import fs from "node:fs";
import path from "node:path";
const ML_ROOT = path.resolve("docs/mlops_evidence/sample_artifacts");
const fsStorage = {
  list: async prefix => { const base = path.join(ML_ROOT, prefix.replace(/^vercel-lab\//, "")); if (!fs.existsSync(base)) return [];
    const out = []; const walk = d => fs.readdirSync(d, { withFileTypes: true }).forEach(e => e.isDirectory() ? walk(path.join(d, e.name)) : out.push("vercel-lab/" + path.relative(ML_ROOT, path.join(d, e.name)).replace(/\\/g, "/"))); walk(base); return out; },
  getJson: async key => { const f = path.join(ML_ROOT, key.replace(/^vercel-lab\//, "")); return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, "utf8")) : null; },
};
const callWith = (sql, deps, method, query, body) => new Promise(resolve => {
  let status = 200, json = null;
  const res = { setHeader() {}, status(c) { status = c; return this; }, json(v) { json = v; resolve({ status, json }); return this; } };
  process.env.CLASSROOM_LAB_ADMIN_KEY = process.env.CLASSROOM_LAB_ADMIN_KEY || "test-key";
  labForecast({ method, query, body, headers: { host: "app.test", origin: "https://app.test" } }, res, { sql, ...deps });
});

test("MLOps: June evidence is a Historical Evaluation (insufficient validation), kept apart from official and experiment runs", async () => {
  const r = await callWith(fakeSql([0, 1, 2, 3, 4]), { mlopsStorage: fsStorage }, "GET", { fc: "mlops", month: "2026-06" });
  assert.equal(r.status, 200);
  assert.equal(r.json.official_linked.latest, null);                              // June was sealed before MLOps existed: nothing is faked
  assert.equal(r.json.experiment_only.latest, null);
  const h = r.json.historical_evaluation.latest;
  assert.equal(h.kind, "HISTORICAL_EVALUATION"); assert.equal(h.report.evaluation_status, "EXPERIMENTAL_INSUFFICIENT_VALIDATION");
  assert.equal(h.report.data_window.valid_origins, 2); assert.equal(h.report.official_selection.method_type, "BASELINE");
  assert.equal(h.report.official_selection.shop_prediction, 89967.41);             // equals the sealed June official forecast
  assert.equal(h.drift.auto_retrain, false); assert.equal(h.drift.performance_drift.status, "INSUFFICIENT_EVIDENCE");
  assert.ok(h.feature_set.files.some(f => f.endsWith("features.parquet")) && h.feature_set.point_in_time.no_future_rows);
  assert.deepEqual(Object.keys(h.artifacts).sort(), ["baseline_naive_previous_month", "baseline_trailing_3_month_mean", "ridge_base", "ridge_marketing"]);
});

test("MLOps: July is an Experiment Only run and is never presented as an official forecast", async () => {
  const r = await callWith(fakeSql([0, 1, 2, 3, 4, 5]), { mlopsStorage: fsStorage }, "GET", { fc: "mlops", month: "2026-07" });
  assert.equal(r.status, 200);
  const e = r.json.experiment_only.latest;
  assert.equal(e.kind, "EXPERIMENT_ONLY"); assert.equal(e.report.evaluation_status, "ELIGIBLE");
  assert.equal(r.json.official_linked.latest, null); assert.equal(r.json.historical_evaluation.latest, null);
  assert.equal(e.status.official_selection_changed, false);
  assert.equal((await callWith(fakeSql([]), { mlopsStorage: fsStorage }, "GET", { fc: "mlops", month: "2026-13" })).status, 400);
});

test("MLOps: a storage outage returns a plain error and never breaks the forecast API", async () => {
  const broken = { list: async () => { throw new Error("boom"); }, getJson: async () => null };
  const bad = await callWith(fakeSql([0, 1, 2, 3, 4]), { mlopsStorage: broken }, "GET", { fc: "mlops", month: "2026-06" });
  assert.equal(bad.status, 503); assert.equal(bad.json.error_code, "MLOPS_STORAGE_UNAVAILABLE");
  const st = await callWith(fakeSql([0, 1, 2, 3, 4]), { mlopsStorage: broken }, "GET", { fc: "status" });
  assert.equal(st.status, 200); assert.equal(st.json.readiness.ready, true);
});

test("MLOps: tickets can only be non-official kinds, after the gate, with a published cutoff, and require an actor", async () => {
  const sql = fakeSql([0, 1, 2, 3, 4]);
  const post = body => callWith(sql, {}, "POST", { fc: "mlops_run" }, body);
  assert.equal((await post({ month: "2026-06", kind: "OFFICIAL_LINKED", actor: "a" })).status, 400);
  assert.equal((await post({ month: "2026-06", kind: "EXPERIMENT_ONLY" })).status, 400);
  assert.equal((await post({ month: "2026-05", kind: "HISTORICAL_EVALUATION", actor: "a" })).status, 409);
  const gap = await post({ month: "2026-08", kind: "EXPERIMENT_ONLY", actor: "a" });
  assert.equal(gap.status, 409); assert.equal(gap.json.error_code, "CUTOFF_NOT_PUBLISHED");
  const ok = await post({ month: "2026-06", kind: "HISTORICAL_EVALUATION", actor: "a" });
  assert.equal(ok.status, 202); assert.ok(ok.json.ticket); assert.equal(ok.json.post_hoc_actual, false);   // June not published yet => no post-hoc actual
  const claim = JSON.parse(Buffer.from(ok.json.ticket.split(".")[0], "base64url").toString());
  assert.equal(claim.action, "mlops"); assert.equal(claim.kind, "HISTORICAL_EVALUATION");
});

// ---- Champion-Challenger monitoring API (artifacts written by the REAL Jan->Oct worker journey, docs/mlops_evidence/monitoring_journey) ----
const MON_ROOT = path.resolve("docs/mlops_evidence/monitoring_journey");
const monStorage = { list: async () => [], getJson: async key => { const f = path.join(MON_ROOT, key.replace(/^vercel-lab\//, "")); return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, "utf8")) : null; } };

test("Monitoring: API returns the newest immutable summary of the current cycle (4 counted months, Preliminary, no recommendation yet)", async () => {
  const cycle = Number(fs.readFileSync(path.join(MON_ROOT, "cycle.txt"), "utf8"));
  const sql = { query: async text => text.includes("dataset_state") ? [{ phase: "RUN2_READY", cycle_number: cycle, last_run_id: "11111111-1111-4111-8111-111111111111" }] : [] };
  const r = await callWith(sql, { mlopsStorage: monStorage }, "GET", { fc: "monitoring" });
  assert.equal(r.status, 200); const s = r.json.summary;
  assert.equal(s.through_month, "2026-10"); assert.equal(s.counted_months, 4); assert.equal(s.evidence_level, "PRELIMINARY");
  assert.equal(s.recommendation.status, "PRELIMINARY_NOT_ASSESSED"); assert.equal(s.recommendation.auto_switch_champion, false); assert.equal(s.recommendation.auto_retrain, false);
  assert.deepEqual(s.monthly.map(m => m.month), ["2026-06", "2026-07", "2026-08", "2026-10"]);        // 2026-09 was not recorded, so it is not guessed afterwards
  assert.equal(s.pair.challenger, "ridge_base"); assert.ok(!JSON.stringify(s).includes("ridge_marketing_in_pair"));
  const absB = s.rows.reduce((a, x) => a + x.baseline.shop_abs_error, 0), act = s.rows.reduce((a, x) => a + x.actual.shop, 0);
  assert.ok(Math.abs(s.cumulative.baseline.wape_pct - 100 * absB / act) < 1e-6);                         // sum|err| / sum(actual), not a mean of monthly WAPE
  const other = await callWith({ query: async text => text.includes("dataset_state") ? [{ phase: "x", cycle_number: cycle + 1, last_run_id: "11111111-1111-4111-8111-111111111111" }] : [] }, { mlopsStorage: monStorage }, "GET", { fc: "monitoring" });
  assert.equal(other.json.summary, null);                                                                // another cycle never sees this cycle's months
});

test("Monitoring: storage outage is a plain 503 and the forecast status keeps working; status exposes which months are published", async () => {
  const bad = await callWith(fakeSql([0, 1, 2, 3, 4]), { mlopsStorage: { list: async () => [], getJson: async () => { throw new Error("down"); } } }, "GET", { fc: "monitoring" });
  assert.equal(bad.status, 503); assert.equal(bad.json.error_code, "MLOPS_STORAGE_UNAVAILABLE");
  const st = await callWith(fakeSql([0, 1, 2, 3, 4]), {}, "GET", { fc: "status" });
  assert.equal(st.json.months.find(m => m.month === "2026-05").published, true); assert.equal(st.json.months.find(m => m.month === "2026-06").published, false);
});
