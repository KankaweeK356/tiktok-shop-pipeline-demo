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

  const STAGE_ORDER = ["ingest", "extract", "transform", "load", "validate"];
  const MONTH_STATUS = {
    PUBLISHED: ["Published", "เผยแพร่แล้ว", "ok"], RUNNING: ["Running", "กำลังรัน", "run"],
    DATA_QUALITY_BLOCKED: ["Blocked by DQ", "ถูกบล็อกโดย Data Quality", "bad"],
    SYSTEM_FAILED: ["Failed by system", "ระบบล้มเหลว (ลองใหม่ได้)", "bad"],
    RUNNABLE: ["Ready to Run", "พร้อมรัน", "ready"], LOCKED: ["Not yet processed", "ยังไม่ถึงคิว", "idle"], UNKNOWN: ["Not verified", "ยังตรวจสอบไม่ได้", "idle"]
  };
  /** One row per delivery month. Backend `months` is the source of truth; runs are only a fallback when it is absent. */
  function monthRows({ months, runs, monthLabels }) {
    const byBatch = Object.fromEntries((months || []).map(m => [m.batch, m]));
    const slots = runsByBatch(runs);
    return DELIVERIES.map((batch, i) => {
      const m = byBatch[batch];
      let state = m ? m.state : null, reason = m ? m.reason : null;
      if (!state) {
        const c = chipStatus(batch, runs);
        state = c === "PUBLISHED" ? "PUBLISHED" : c === "BLOCKED_DQ" ? "DATA_QUALITY_BLOCKED" : c === "FAILED" ? "SYSTEM_FAILED" : c === "RUNNING" ? "RUNNING" : "UNKNOWN";
      }
      const slot = slots[batch] || {};
      const run = m?.run_id ? { run_id: m.run_id } : (slot.succeeded || slot.blocked || slot.failed || slot.active || null);
      const lastStage = m?.last_stage || null, idx = STAGE_ORDER.indexOf(lastStage);
      const stagesDone = state === "PUBLISHED" ? 5 : (state === "DATA_QUALITY_BLOCKED" || state === "SYSTEM_FAILED") && idx >= 0 ? idx : null;
      const meta = MONTH_STATUS[state] || MONTH_STATUS.UNKNOWN;
      return { batch, month: monthLabels?.[batch] || "2026-" + String(i + 1).padStart(2, "0"), state, reason, label: meta[0], thai: meta[1], tone: meta[2],
        runId: run ? String(run.run_id) : null, lastStage, stagesDone, publishedAt: null };
    });
  }
  /** Operational summary. Missing data is reported as NOT_VERIFIED, never as 0 / PASS. */
  function opsOverview({ loaded, phase, rows, runs, latestFailed, dq, active, snapshots, publishedThrough }) {
    const total = DELIVERIES.length;
    if (!loaded) return { verified: false, pipeline: "NOT_VERIFIED", dq: "NOT_VERIFIED", published: null, total, warehouse: "NOT_VERIFIED", action: null, last: null };
    const published = rows.filter(r => r.state === "PUBLISHED").length;
    const blocked = rows.find(r => r.state === "DATA_QUALITY_BLOCKED");
    const failed = rows.find(r => r.state === "SYSTEM_FAILED") || (latestFailed ? { batch: latestFailed.batch } : null);
    const running = rows.find(r => r.state === "RUNNING") || (active ? { batch: null } : null);
    const next = rows.find(r => r.state === "RUNNABLE");
    const pipeline = running ? "RUNNING" : blocked ? "BLOCKED" : failed ? "FAILED" : published === total ? "COMPLETED" : next ? "READY" : "WAITING";
    const dqStatus = dq?.schemaMissing ? "NOT_VERIFIED" : blocked ? (dq?.ready || blocked.reason === "READY_TO_RESUME" ? "PENDING" : "FAILED") : published > 0 ? "PASSED" : "NOT_CHECKED";
    const succeeded = (runs || []).filter(r => r.status === "SUCCEEDED").sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0] || null;
    const snap = (snapshots || []).filter(s => s.is_current).pop() || (snapshots || []).slice(-1)[0] || null;
    const warehouse = published === 0 ? "NOT_PUBLISHED" : !Array.isArray(snapshots) || !snap ? "NOT_VERIFIED" : "PUBLISHED";
    let action = null;
    if (pipeline === "BLOCKED") action = { kind: "REVIEW_FIX", batch: blocked.batch };
    else if (pipeline === "FAILED") action = { kind: "RETRY", batch: failed.batch };
    else if (pipeline === "READY") action = { kind: "RUN", batch: next.batch };
    else if (pipeline === "RUNNING") action = { kind: "WAIT", batch: running.batch };
    else if (pipeline === "WAITING") action = { kind: "PREREQUISITE", batch: null };
    return { verified: true, phase, pipeline, dq: dqStatus, published, total, warehouse, publishedThrough: publishedThrough || null,
      snapshot: snap ? { batch: snap.batch, runId: snap.run_id, publishedAt: snap.published_at, sourceVersion: snap.source_version } : null,
      last: succeeded ? { runId: String(succeeded.run_id), batch: runBatch(succeeded), startedAt: succeeded.created_at } : null, action };
  }
  return { DELIVERIES, STAGE_ORDER, canonicalBatch, runBatch, runsByBatch, chipStatus, stageView, makeSequencer, monthRows, opsOverview };
});
