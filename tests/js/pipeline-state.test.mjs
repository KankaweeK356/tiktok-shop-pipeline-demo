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
