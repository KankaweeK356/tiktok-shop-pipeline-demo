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
    labForecast({ method, query, body, headers: { host: "app.test", origin: "https://app.test", ...headers } }, res, { sql });
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
  const post = body => callWith(sql, { mlopsStorage: { getJson: async () => null, list: async () => [] } }, "POST", { fc: "mlops_run" }, body);
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

// ---- Champion-Challenger monitoring API (artifacts written by the REAL Jan->Oct worker journey: docs/mlops_evidence/local_real_source_test) ----
import { readMonitoring } from "../../lib/lab-mlops.js";
const MON_ROOT = path.resolve("docs/mlops_evidence/local_real_source_test/monitoring_journey");
const monStorage = { list: async () => [], getJson: async key => { const f = path.join(MON_ROOT, key.replace(/^vercel-lab\//, "")); return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, "utf8")) : null; } };
const journeySql = cycle => ({ query: async text => text.includes("dataset_state") ? [{ phase: "RUN2_READY", cycle_number: cycle, last_run_id: "11111111-1111-4111-8111-111111111111" }]
  : text.includes("pipeline_runs") ? DELIVERIES.map((b, i) => ({ run_id: "22222222-2222-4222-8222-22222222222" + i, status: "SUCCEEDED", batch: b })) : [] });

test("Monitoring: API returns the newest summary revision of the current stream (5 counted months after September was recovered, Preliminary, labelled LOCAL_REAL_SOURCE_TEST)", async () => {
  const cycle = Number(fs.readFileSync(path.join(MON_ROOT, "cycle.txt"), "utf8"));
  const r = await callWith(journeySql(cycle), { mlopsStorage: monStorage }, "GET", { fc: "monitoring" });
  assert.equal(r.status, 200); const s = r.json.summary;
  assert.equal(r.json.stream, `lab-cycle-${cycle}`); assert.equal(s.data_origin, "LOCAL_REAL_SOURCE_TEST");
  assert.equal(s.through_month, "2026-10"); assert.equal(s.counted_months, 5); assert.equal(s.evidence_level, "PRELIMINARY");
  assert.equal(s.recommendation.status, "PRELIMINARY_NOT_ASSESSED"); assert.equal(s.recommendation.auto_switch_champion, false); assert.equal(s.recommendation.auto_retrain, false);
  assert.equal(s.recommendation.champion_change_function_in_system, false);
  assert.deepEqual(s.monthly.map(m => m.month), ["2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]);   // 2026-09 failed once, then was recovered from original evidence (newest revision)
  assert.equal(s.pair.champion, "OFFICIAL_BASELINE_OF_EACH_MONTH"); assert.equal(s.pair.challenger, "ridge_base");
  assert.ok(Object.values(s.champion_models_by_month).every(m => /^baseline_/.test(m)));
  const absB = s.rows.reduce((a, x) => a + x.baseline.shop_abs_error, 0), act = s.rows.reduce((a, x) => a + x.actual.shop, 0);
  assert.ok(Math.abs(s.cumulative.baseline.wape_pct - 100 * absB / act) < 1e-6);                         // sum|err| / sum(actual), not a mean of monthly WAPE
  const other = await callWith(journeySql(cycle + 1), { mlopsStorage: monStorage }, "GET", { fc: "monitoring" });
  assert.equal(other.json.summary, null);                                                                // another cycle (stream) never sees this cycle's months
});

test("Monitoring: reads a long-term stream across a year boundary without any fixed calendar range", async () => {
  const summary = { stream: "long", through_month: "2027-01", counted_months: 3 };
  const store = { getJson: async key => key.endsWith("/monitoring/long/summary/through=2027-01.json") ? summary : null };
  process.env.CLASSROOM_MONITORING_STREAM = "long";
  try {
    assert.deepEqual((await readMonitoring(7, "2027-03", { mlopsStorage: store })).summary, summary);   // newest published month had no summary: probes back to Jan 2027
    assert.equal((await readMonitoring(7, "2030-06", { mlopsStorage: store })).summary, null);          // outside the 36-month rolling window
    assert.equal((await readMonitoring(7, null, { mlopsStorage: store })).summary, null);
  } finally { delete process.env.CLASSROOM_MONITORING_STREAM; }
});

test("Monitoring: storage outage is a plain 503 and the forecast status keeps working; status exposes which months are published", async () => {
  const bad = await callWith(journeySql(1), { mlopsStorage: { list: async () => [], getJson: async () => { throw new Error("down"); } } }, "GET", { fc: "monitoring" });
  assert.equal(bad.status, 503); assert.equal(bad.json.error_code, "MLOPS_STORAGE_UNAVAILABLE");
  const st = await callWith(fakeSql([0, 1, 2, 3, 4]), {}, "GET", { fc: "status" });
  assert.equal(st.json.months.find(m => m.month === "2026-05").published, true); assert.equal(st.json.months.find(m => m.month === "2026-06").published, false);
});


// ---- Public API protection (no login): browser provenance, server-side gates, idempotency, caps, no leaked secrets -----------------
import { strictOrigin, MAX_DRAFTS_PER_MONTH, MAX_SIM_BASKETS } from "../../lib/lab-forecast.js";
const noStore = { getJson: async () => null, list: async () => [] };
const callRaw = (sql, deps, method, query, body, headers) => new Promise(resolve => {
  let status = 200, json = null;
  const res = { setHeader() {}, status(c) { status = c; return this; }, json(v) { json = v; resolve({ status, json }); return this; } };
  process.env.CLASSROOM_LAB_ADMIN_KEY = process.env.CLASSROOM_LAB_ADMIN_KEY || "test-key";
  labForecast({ method, query, body, headers }, res, { sql, ...deps });
});
const POSTS = [["generate", { month: "2026-06", actor: "a" }], ["seal", { forecast_run_id: "x", actor: "a" }], ["simulate", { month: "2026-06", baskets: [], controls: {}, assumptions: {} }],
  ["seal_plan", { month: "2026-06", actor: "a" }], ["mlops_run", { month: "2026-06", kind: "EXPERIMENT_ONLY", actor: "a" }], ["monitoring_repair", {}]];

test("Security layer 1: every POST needs browser provenance; header-less (curl) and cross-site calls are refused before any database access", async () => {
  let touched = 0; const sql = { query: async () => { touched += 1; return []; } };
  for (const [op, body] of POSTS) {
    for (const headers of [{ host: "app.test" }, { host: "app.test", origin: "https://evil.test" }, { host: "app.test", "sec-fetch-site": "cross-site" }, { host: "app.test", origin: "not a url" }]) {
      const r = await callRaw(sql, { mlopsStorage: noStore }, "POST", { fc: op }, body, headers);
      assert.equal(r.status, 403, `${op} ${JSON.stringify(headers)}`); assert.equal(r.json.error_code, "ORIGIN_REQUIRED");
    }
  }
  assert.equal(touched, 0);
  assert.equal(strictOrigin({ headers: { host: "app.test", origin: "https://app.test" } }), true);
  assert.equal(strictOrigin({ headers: { host: "app.test", "sec-fetch-site": "same-origin" } }), true);
  assert.equal(strictOrigin({ headers: { host: "app.test" } }), false);
});

test("Security layer 1b: provenance is not authorization: a forged same-origin call still hits the server-side gates (state, cutoff, sealed month)", async () => {
  const ok = { host: "app.test", origin: "https://app.test" };
  const r = await callRaw(fakeSql([0, 1, 2]), { mlopsStorage: noStore }, "POST", { fc: "generate" }, { month: "2026-06", actor: "forged" }, ok);
  assert.equal(r.status, 409); assert.equal(r.json.error_code, "CUTOFF_NOT_PUBLISHED");                       // history/cutoff checked on the server, not trusted from the client
  const seal = await callRaw(fakeSql([0, 1, 2, 3, 4]), {}, "POST", { fc: "seal" }, { forecast_run_id: "not-a-uuid", actor: "x" }, ok);
  assert.equal(seal.status, 400);
});

test("Security layer 2a: drafts per month are capped and the simulation size is bounded", async () => {
  const ok = { host: "app.test", origin: "https://app.test" };
  const sqlWith = n => ({ query: async text => {
    if (text.includes("demo_control.dataset_state")) return [{ phase: "RUN2_READY", cycle_number: 7, last_run_id: "11111111-1111-4111-8111-111111111111" }];
    if (text.includes("demo_control.pipeline_runs")) return [0, 1, 2, 3, 4].map(i => ({ run_id: "22222222-2222-4222-8222-22222222222" + i, status: "SUCCEEDED", batch: DELIVERIES[i] }));
    if (text.includes("FROM demo_ml.forecast_run")) return Array.from({ length: n }, (_, i) => ({ forecast_run_id: "33333333-3333-4333-8333-33333333333" + i, is_official: false, status: "DRAFT" }));
    return []; } });
  assert.equal((await callRaw(sqlWith(MAX_DRAFTS_PER_MONTH - 1), {}, "POST", { fc: "generate" }, { month: "2026-06", actor: "a" }, ok)).status, 202);
  const capped = await callRaw(sqlWith(MAX_DRAFTS_PER_MONTH), {}, "POST", { fc: "generate" }, { month: "2026-06", actor: "a" }, ok);
  assert.equal(capped.status, 429); assert.equal(capped.json.error_code, "DRAFT_LIMIT");
  const big = await callRaw(sqlWith(0), {}, "POST", { fc: "simulate" }, { month: "2026-06", baskets: Array.from({ length: MAX_SIM_BASKETS + 1 }, () => ({ orders: 1, lines: [] })), controls: {}, assumptions: {} }, ok);
  assert.equal(big.status, 413);
  const fat = await callRaw(sqlWith(0), {}, "POST", { fc: "simulate" }, { month: "2026-06", baskets: [{ orders: 1, lines: Array.from({ length: 51 }, () => ({})) }], controls: {}, assumptions: {} }, ok);
  assert.equal(fat.status, 413);
});

test("Security layer 2b: an ML evidence request is idempotent and fails closed when repeats cannot be ruled out", async () => {
  const ok = { host: "app.test", origin: "https://app.test" }, sql = fakeSql([0, 1, 2, 3, 4]), seen = [];
  const store = { list: async () => [], getJson: async key => { seen.push(key); return /requests\/HISTORICAL_EVALUATION\/2026-06\//.test(key) ? { training_run_id: "run-1" } : null; } };
  const repeat = await callRaw(sql, { mlopsStorage: store }, "POST", { fc: "mlops_run" }, { month: "2026-06", kind: "HISTORICAL_EVALUATION", actor: "a" }, ok);
  assert.equal(repeat.status, 200); assert.equal(repeat.json.already_recorded, true); assert.equal(repeat.json.ticket, undefined);     // no ticket, no worker run, no new files
  const fresh = await callRaw(sql, { mlopsStorage: store }, "POST", { fc: "mlops_run" }, { month: "2026-06", kind: "EXPERIMENT_ONLY", actor: "a" }, ok);
  assert.equal(fresh.status, 202); assert.ok(fresh.json.ticket);
  const down = await callRaw(sql, { mlopsStorage: { list: async () => [], getJson: async () => { throw new Error("down"); } } }, "POST", { fc: "mlops_run" }, { month: "2026-06", kind: "EXPERIMENT_ONLY", actor: "a" }, ok);
  assert.equal(down.status, 503);
  assert.ok(seen.some(k => k.includes("-none.json")));
});

test("Recovery API: no ticket and no worker run unless an evaluation or summary is really missing", async () => {
  const ok = { host: "app.test", origin: "https://app.test" };
  const sql = { query: async text => {
    if (text.includes("demo_control.dataset_state")) return [{ phase: "RUN2_READY", cycle_number: 7, last_run_id: "11111111-1111-4111-8111-111111111111" }];
    if (text.includes("demo_control.pipeline_runs")) return DELIVERIES.slice(0, 7).map((b, i) => ({ run_id: "22222222-2222-4222-8222-22222222222" + i, status: "SUCCEEDED", batch: b }));
    if (text.includes("FROM demo_ml.forecast_run")) return [{ forecast_run_id: "44444444-4444-4444-8444-444444444444", is_official: true, status: "SEALED" }];
    if (text.includes("demo_ml.forecast_result")) return [];
    return []; } };
  const full = { list: async () => [], getJson: async () => ({ ok: true }) };
  const none = await callRaw(sql, { mlopsStorage: full }, "POST", { fc: "monitoring_repair" }, {}, ok);
  assert.equal(none.status, 200); assert.equal(none.json.nothing_to_repair, true); assert.equal(none.json.ticket, undefined);
  const halfStore = { list: async () => [], getJson: async key => key.includes("/evaluations/") ? { month: "x" } : null };       // evaluation exists, summary missing
  const gap = await callRaw(sql, { mlopsStorage: halfStore }, "POST", { fc: "monitoring_repair" }, {}, ok);
  assert.equal(gap.status, 202); assert.ok(gap.json.ticket); assert.ok(gap.json.gaps.every(g => g.missing === "summary"));
  const claim = JSON.parse(Buffer.from(gap.json.ticket.split(".")[0], "base64url").toString());
  assert.equal(claim.action, "monitoring_repair"); assert.equal(claim.kind, undefined);
  const read = await callRaw(sql, { mlopsStorage: halfStore }, "GET", { fc: "monitoring" }, undefined, ok);
  assert.equal(read.status, 200); assert.ok(read.json.gaps.length > 0);                                                     // the page can offer the repair
});

test("No secret or storage detail leaks through API error bodies", async () => {
  const ok = { host: "app.test", origin: "https://app.test" };
  const leaky = { query: async () => { throw new Error("connect ECONNREFUSED postgres://user:SECRETPW@db.example/neon sslmode=require"); } };
  for (const [op, body] of POSTS.slice(0, 5)) {
    const r = await callRaw(leaky, { mlopsStorage: noStore }, "POST", { fc: op }, body, ok);
    assert.ok(!JSON.stringify(r.json).includes("SECRETPW") && !JSON.stringify(r.json).includes("postgres://"), op);
  }
  const leakyStore = { list: async () => { throw new Error("S3 https://secret-bucket.example.com AccessKeyId=AKIA123"); }, getJson: async () => { throw new Error("AKIA123 secret-bucket"); } };
  const r = await callRaw(fakeSql([0, 1, 2, 3, 4]), { mlopsStorage: leakyStore }, "GET", { fc: "mlops", month: "2026-06" }, undefined, ok);
  assert.ok(!JSON.stringify(r.json).includes("AKIA") && !JSON.stringify(r.json).includes("secret-bucket"));
});
