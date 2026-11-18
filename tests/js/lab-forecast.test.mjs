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
