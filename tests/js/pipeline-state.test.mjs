import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
// The helper is a plain browser script (package.json is "type": "module"), so evaluate it as one.
const sandbox = { self: {} };
vm.runInNewContext(readFileSync(new URL("../../dashboard/pipeline-state.js", import.meta.url), "utf8"), sandbox);
const S = sandbox.self.PipelineState;

const run = (batch, status, t = "2026-11-17T10:00:00Z", extra = {}) =>
  ({ run_id: `${batch}-${status}`, source_batch: batch, status, created_at: t, run_type: batch === "initial" ? "RUN1" : "RUN2", ...extra });

test("canonical batch keys", () => {
  assert.equal(S.canonicalBatch("incremental_01"), "incremental_01");
  assert.equal(S.canonicalBatch("2026-02"), "incremental_01");
  assert.equal(S.canonicalBatch("incremental"), "");
});

test("February SUCCEEDED chip and stage detail agree even while March is blocked", () => {
  const runs = [run("initial", "SUCCEEDED"), run("incremental_01", "SUCCEEDED"), run("incremental_02", "BLOCKED_DQ")];
  assert.equal(S.chipStatus("incremental_01", runs), "PUBLISHED");
  assert.equal(S.chipStatus("incremental_02", runs), "BLOCKED_DQ");
  const dq = { blocked: true, run: { batch: "incremental_02", failed_stage: "ingest", run_id: "r3" } };
  // February evidence present -> shown
  const results = { incremental_01: { ingest: { evidence: { x: 1 }, runId: "r2" } } };
  assert.equal(S.stageView({ batch: "incremental_01", stage: "ingest", results, runs, dq }).kind, "EVIDENCE");
  // February succeeded but a stage receipt is missing -> EVIDENCE_UNAVAILABLE with the real run id, never WAITING
  const missing = S.stageView({ batch: "incremental_01", stage: "load", results, runs, dq });
  assert.equal(missing.kind, "EVIDENCE_UNAVAILABLE");
  assert.equal(missing.runId, "incremental_01-SUCCEEDED");
  // March: blocked stage is marked BLOCKED, later stages WAITING
  assert.equal(S.stageView({ batch: "incremental_02", stage: "ingest", results, runs, dq }).kind, "BLOCKED");
  assert.equal(S.stageView({ batch: "incremental_02", stage: "extract", results, runs, dq }).kind, "WAITING");
});

test("latest run wins and an older failure does not hide a later success", () => {
  const runs = [run("incremental_01", "FAILED", "2026-11-17T09:00:00Z"), run("incremental_01", "SUCCEEDED", "2026-11-17T10:00:00Z")];
  assert.equal(S.chipStatus("incremental_01", runs), "PUBLISHED");
});

test("sequencer drops stale async responses", () => {
  const seq = S.makeSequencer();
  const first = seq.next(), second = seq.next();
  assert.equal(seq.isCurrent(first), false);
  assert.equal(seq.isCurrent(second), true);
});

// ---- Data Operations overview: what the admin summary says must follow backend state ----
const mk = (n, over = {}) => S.DELIVERIES.map((batch, i) => ({ batch, month: "2026-" + String(i + 1).padStart(2, "0"),
  state: i < n ? "PUBLISHED" : i === n ? "RUNNABLE" : "LOCKED", reason: i > n ? "PREVIOUS_MONTH_NOT_PUBLISHED" : null, last_stage: null, run_id: i < n ? "r" + i : null, ...(over[i] || {}) }));
const ovr = (months, extra = {}) => {
  const runs = months.filter(m => m.state === "PUBLISHED").map((m, i) => run(m.batch, "SUCCEEDED", "2026-11-17T1" + i + ":00:00Z"));
  const rows = S.monthRows({ months, runs });
  return S.opsOverview({ loaded: true, phase: "RUN2_READY", rows, runs, latestFailed: null, dq: {}, active: null,
    snapshots: [{ batch: "incremental_01", run_id: "r1", published_at: "2026-11-17T10:00:00Z", is_current: true, source_version: "v" }], publishedThrough: "2026-02", ...extra });
};

test("overview: not loaded is NOT_VERIFIED, never zero or pass", () => {
  const o = S.opsOverview({ loaded: false });
  assert.equal(o.pipeline, "NOT_VERIFIED"); assert.equal(o.dq, "NOT_VERIFIED"); assert.equal(o.published, null); assert.equal(o.warehouse, "NOT_VERIFIED");
});
test("overview: 2 months published, next runnable -> Ready, 2/10, DQ passed", () => {
  const o = ovr(mk(2));
  assert.equal(o.pipeline, "READY"); assert.equal(o.published, 2); assert.equal(o.total, 10); assert.equal(o.dq, "PASSED"); assert.equal(o.action.kind, "RUN"); assert.equal(o.action.batch, "incremental_02");
  assert.equal(o.warehouse, "PUBLISHED");
});
test("overview: March DQ-blocked -> Blocked + Review&Fix, published count excludes March, warehouse not claiming March", () => {
  const m = mk(2, { 2: { state: "DATA_QUALITY_BLOCKED", reason: "BLOCKED_DQ", last_stage: "ingest", run_id: "r2" } });
  const o = ovr(m);
  assert.equal(o.pipeline, "BLOCKED"); assert.equal(o.dq, "FAILED"); assert.equal(o.published, 2); assert.equal(o.action.kind, "REVIEW_FIX"); assert.equal(o.action.batch, "incremental_02");
  const rows = S.monthRows({ months: m, runs: [] });
  assert.equal(rows[2].label, "Blocked by DQ"); assert.equal(rows[2].stagesDone, 0); assert.equal(rows[1].stagesDone, 5);
  assert.equal(ovr(m, { publishedThrough: "2026-02" }).publishedThrough, "2026-02");
});
test("overview: READY_TO_RESUME after correction is Pending, not Failed", () => {
  const o = ovr(mk(2, { 2: { state: "DATA_QUALITY_BLOCKED", reason: "READY_TO_RESUME", last_stage: "ingest" } }));
  assert.equal(o.dq, "PENDING");
});
test("overview: system failure is Failed with Retry, not a DQ failure", () => {
  const o = ovr(mk(2, { 2: { state: "SYSTEM_FAILED", reason: "RETRYABLE", last_stage: "load" } }));
  assert.equal(o.pipeline, "FAILED"); assert.equal(o.action.kind, "RETRY"); assert.equal(o.dq, "PASSED");
  assert.equal(S.monthRows({ months: mk(2, { 2: { state: "SYSTEM_FAILED", last_stage: "load" } }), runs: [] })[2].stagesDone, 3);
});
test("overview: running month wins over everything", () => {
  assert.equal(ovr(mk(2, { 2: { state: "RUNNING" } })).pipeline, "RUNNING");
});
test("overview: missing snapshot list is NOT_VERIFIED, no published month is NOT_PUBLISHED, 10 months is Completed", () => {
  assert.equal(ovr(mk(2), { snapshots: null }).warehouse, "NOT_VERIFIED");
  assert.equal(ovr(mk(0)).warehouse, "NOT_PUBLISHED"); assert.equal(ovr(mk(0)).dq, "NOT_CHECKED");
  const all = ovr(mk(10)); assert.equal(all.pipeline, "COMPLETED"); assert.equal(all.action, null);
});
test("monthRows falls back to runs when backend months are absent (and never invents Published)", () => {
  const rows = S.monthRows({ months: [], runs: [run("initial", "SUCCEEDED"), run("incremental_01", "BLOCKED_DQ")] });
  assert.equal(rows[0].state, "PUBLISHED"); assert.equal(rows[1].state, "DATA_QUALITY_BLOCKED"); assert.equal(rows[2].state, "UNKNOWN");
});

// ---- Source card facts: expected identity from the Source Lock, recorded identity only from backend runs ----
const lock = { source_version: "classroom_v2_2026_11_16", zip_filename_template: "classroom-source-{month}.zip",
  months: { "2026-02": { batch: "incremental_01", zip_sha256: "aa" }, "2026-03": { batch: "incremental_02", zip_sha256: "bb" } } };
test("source card: no lock -> NOT_VERIFIED (never 'validated')", () => {
  const f = S.sourceFacts({ batch: "incremental_02", month: "2026-03", lock: null, runs: [], dq: {}, snapshots: [] });
  assert.equal(f.fileState, "NOT_VERIFIED"); assert.equal(f.hashState, "NOT_VERIFIED"); assert.equal(f.dqState, "NOT_CHECKED");
});
test("source card: lock known, month not run yet -> file READY, hash NOT_CHECKED, DQ not checked; file name from the lock template", () => {
  const f = S.sourceFacts({ batch: "incremental_02", month: "2026-03", lock, runs: [], dq: {}, snapshots: [] });
  assert.equal(f.file, "classroom-source-2026-03.zip"); assert.equal(f.fileState, "READY"); assert.equal(f.hashState, "NOT_CHECKED"); assert.equal(f.expected, "bb");
});
test("source card: March blocked by DQ -> hash VERIFIED against the lock while DQ FAILED (two separate facts)", () => {
  const runs = [run("incremental_02", "BLOCKED_DQ", "2026-11-17T10:00:00Z", { source_zip_sha256: "bb", source_version: "classroom_v2_2026_11_16" })];
  const dq = { blocked: true, run: { batch: "incremental_02", failed_stage: "ingest" }, issues: [{ status: "OPEN" }, { status: "RESOLVED" }] };
  const f = S.sourceFacts({ batch: "incremental_02", month: "2026-03", lock, runs, dq, snapshots: [] });
  assert.equal(f.hashState, "VERIFIED"); assert.equal(f.dqState, "FAILED"); assert.equal(f.openIssues, 1);
});
test("source card: recorded hash different from the lock -> MISMATCH; wrong version flagged", () => {
  const runs = [run("incremental_01", "SUCCEEDED", "2026-11-17T10:00:00Z", { source_zip_sha256: "zz", source_version: "other" })];
  const f = S.sourceFacts({ batch: "incremental_01", month: "2026-02", lock, runs, dq: {}, snapshots: [] });
  assert.equal(f.hashState, "MISMATCH"); assert.equal(f.versionMismatch, true); assert.equal(f.dqState, "PASSED");
});
test("source card: CANCELLED runs are ignored; hash can fall back to the published snapshot", () => {
  const runs = [run("incremental_01", "CANCELLED", "2026-11-17T12:00:00Z", { source_zip_sha256: "zz" })];
  const f = S.sourceFacts({ batch: "incremental_01", month: "2026-02", lock, runs, dq: {}, snapshots: [{ batch: "incremental_01", source_zip_sha256: "aa" }] });
  assert.equal(f.hashState, "VERIFIED");
});
test("reconciliation: only MATCH with real equal numbers; missing evidence is NOT_VERIFIED, differences are MISMATCH", () => {
  const ev = (items, rev, failed = 0) => ({ output: { preview: [{ check: "Checks", source: 9, warehouse: 9 }, { check: "Failed checks", source: 0, warehouse: failed },
    { check: "Paid items", source: items[0], warehouse: items[1] }, { check: "Net revenue", source: rev[0], warehouse: rev[1] }] } });
  assert.equal(S.reconciliation(null).state, "NOT_VERIFIED"); assert.equal(S.reconciliation({ output: {} }).state, "NOT_VERIFIED");
  assert.equal(S.reconciliation(ev([100, 100], [5000.5, 5000.5])).state, "MATCH");
  assert.equal(S.reconciliation(ev([100, 99], [5000.5, 5000.5])).state, "MISMATCH");
  assert.equal(S.reconciliation(ev([100, 100], [5000.5, 4999])).state, "MISMATCH");
  assert.equal(S.reconciliation(ev([100, 100], [5000.5, 5000.5], 2)).state, "MISMATCH");
});
test("reconciliation: real evidence shape ({check:'Checks', passed, failed}) — failed checks block MATCH", () => {
  const real = failed => ({ output: { preview: [{ check: "Checks", passed: 21 - failed, failed }, { check: "Paid items", source: 1147, warehouse: 1147 }, { check: "Net revenue", source: 417092.85, warehouse: 417092.85 }] } });
  assert.equal(S.reconciliation(real(0)).state, "MATCH"); assert.equal(S.reconciliation(real(1)).state, "MISMATCH");
});
