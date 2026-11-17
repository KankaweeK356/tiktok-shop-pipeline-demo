/* Pure helpers that decide what the Pipeline page shows for a month.
 * No DOM, no network: unit-tested with `node --test tests/js`.
 * Rule: what is rendered comes from backend-confirmed runs, never from a UI flag
 * or from a hardcoded month. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PipelineState = api;
})(typeof self !== "undefined" ? self : this, function () {
  const DELIVERIES = ["initial", ...Array.from({ length: 9 }, (_, i) => "incremental_" + String(i + 1).padStart(2, "0"))];
  const BLOCKED = ["BLOCKED_DQ", "READY_TO_RESUME"];

  /** Canonical delivery key: initial, incremental_01 … incremental_09 (accepts month strings too). */
  function canonicalBatch(value) {
    const v = String(value ?? "");
    if (DELIVERIES.includes(v)) return v;
    const m = /^2026-(0[1-9]|10)$/.exec(v);
    return m ? DELIVERIES[Number(m[1]) - 1] : "";
  }
  function runBatch(run) {
    const direct = canonicalBatch(run?.source_batch) || canonicalBatch(run?.batch) || canonicalBatch(run?.source_month);
    if (direct) return direct;
    return run?.run_type === "RUN1" ? "initial" : "";
  }
  /** Latest run per canonical batch, split by outcome. */
  function runsByBatch(runs) {
    const out = {};
    for (const run of runs || []) {
      const batch = runBatch(run);
      if (!batch) continue;
      const slot = out[batch] || (out[batch] = { succeeded: null, blocked: null, failed: null, active: null });
      const key = run.status === "SUCCEEDED" ? "succeeded" : BLOCKED.includes(run.status) ? "blocked" :
        run.status === "FAILED" ? "failed" : ["RUNNING", "QUEUED"].includes(run.status) ? "active" : null;
      if (!key) continue;
      if (!slot[key] || Date.parse(run.created_at) >= Date.parse(slot[key].created_at)) slot[key] = run;
    }
    return out;
  }
  /** Chip status of one month. */
  function chipStatus(batch, runs) {
    const slot = runsByBatch(runs)[batch] || {};
    if (slot.succeeded) return "PUBLISHED";
    if (slot.blocked) return "BLOCKED_DQ";
    if (slot.failed) return "FAILED";
    if (slot.active) return "RUNNING";
    return "NOT_STARTED";
  }
  /** What the stage detail must show for (batch, stage). Evidence is never invented. */
  function stageView({ batch, stage, results, runs, dq }) {
    const saved = results?.[batch]?.[stage]?.evidence ? results[batch][stage] : null;
    if (saved) return { kind: "EVIDENCE", runId: saved.runId || null };
    const slot = runsByBatch(runs)[batch] || {};
    if (dq?.blocked && dq.run?.batch === batch && dq.run.failed_stage === stage)
      return { kind: "BLOCKED", runId: dq.run.run_id };
    if (slot.succeeded) return { kind: "EVIDENCE_UNAVAILABLE", runId: String(slot.succeeded.run_id) };
    if (slot.active) return { kind: "RUNNING", runId: String(slot.active.run_id) };
    return { kind: "WAITING", runId: null };
  }
  /** Reject out-of-order async responses (a previously selected month must not overwrite the view). */
  function makeSequencer() {
    let current = 0;
    return { next: () => ++current, isCurrent: token => token === current };
  }
  return { DELIVERIES, canonicalBatch, runBatch, runsByBatch, chipStatus, stageView, makeSequencer };
});
