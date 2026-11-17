const fs = require('fs');

const path = 'dashboard/app.js';
let code = fs.readFileSync(path, 'utf8');

// 1. Initial state
const oldInit = 'batchResults: { initial: {}, incremental: {} }, batchSummaries: { initial: null, incremental: null },';
const newInit = 'batchResults: Object.fromEntries(["initial", ...Array.from({length: 9}, (_, i) => "incremental_" + String(i + 1).padStart(2, "0"))].map(b => [b, {}])), batchSummaries: Object.fromEntries(["initial", ...Array.from({length: 9}, (_, i) => "incremental_" + String(i + 1).padStart(2, "0"))].map(b => [b, null])),';

if (code.includes(oldInit)) {
  code = code.replace(oldInit, newInit);
  console.log('1. Updated state batchResults & batchSummaries initialization');
} else {
  console.log('1. oldInit not found');
}

const oldBatchRunIds = 'state.batchRunIds = { initial: null, incremental: null };';
const newBatchRunIds = 'state.batchRunIds = Object.fromEntries(["initial", ...Array.from({length: 9}, (_, i) => "incremental_" + String(i + 1).padStart(2, "0"))].map(b => [b, null]));';
if (code.includes(oldBatchRunIds)) {
  code = code.replace(oldBatchRunIds, newBatchRunIds);
  console.log('2. Updated state.batchRunIds initialization');
}

// 2. hydrateCurrentCycleRuns
const oldHydrate = `  async function hydrateCurrentCycleRuns(runs, hasCurrentRun) {
    state.currentCycleRuns = runs;
    if (!hasCurrentRun) {
      state.batchResults = { initial: {}, incremental: {} };
      state.batchSummaries = { initial: null, incremental: null };
      state.batchRunIds = { initial: null, incremental: null };
      if (!["submitting", "queued", "in_progress"].includes(state.batchRun.status))
        state.batchRun = { batch: "", status: "", runId: null, stages: [] };
      return;
    }
    const latestByBatch = {};
    for (const run of runs) {
      if (run.status !== "SUCCEEDED") continue;
      const prior = latestByBatch[run.batch];
      if (!prior || Date.parse(run.created_at) > Date.parse(prior.created_at))
        latestByBatch[run.batch] = run;
    }
    for (const batch of ["initial", "incremental"]) {
      const run = latestByBatch[batch]; if (!run) continue;
      try {
        const response = await fetch("/api/lab-batch-result?run_id=" + encodeURIComponent(run.run_id),
          { cache: "no-store" });
        if (!response.ok) continue;
        const payload = await response.json();
        const result = payload.result; if (!result || result.status !== "SUCCESS") continue;
        state.batchRunIds[batch] = String(run.run_id);
        state.batchSummaries[batch] = {
          runId: String(run.run_id), url: run.url,
          sourceMonth: run.source_month, result
        };
        state.batchResults[batch] = Object.fromEntries((result.stages || []).map(item =>
          [item.stage, { evidence: item.evidence, url: run.url, runId: String(run.run_id) }]));`;

const newHydrate = `  async function hydrateCurrentCycleRuns(runs, hasCurrentRun) {
    state.currentCycleRuns = runs;
    const allDeliveries = ["initial", ...Array.from({length: 9}, (_, i) => "incremental_" + String(i + 1).padStart(2, "0"))];
    if (!hasCurrentRun) {
      state.batchResults = Object.fromEntries(allDeliveries.map(b => [b, {}]));
      state.batchSummaries = Object.fromEntries(allDeliveries.map(b => [b, null]));
      state.batchRunIds = Object.fromEntries(allDeliveries.map(b => [b, null]));
      if (!["submitting", "queued", "in_progress"].includes(state.batchRun.status))
        state.batchRun = { batch: "", status: "", runId: null, stages: [] };
      return;
    }
    const latestByBatch = {};
    for (const run of runs) {
      if (run.status !== "SUCCEEDED") continue;
      const canonicalBatch = run.source_batch || run.batch ||
        (run.run_type === "RUN1" ? "initial" : (run.run_type === "RUN2" ? "incremental_01" : "initial"));
      const prior = latestByBatch[canonicalBatch];
      if (!prior || Date.parse(run.created_at) > Date.parse(prior.created_at))
        latestByBatch[canonicalBatch] = run;
    }
    for (const batch of allDeliveries) {
      const run = latestByBatch[batch]; if (!run) continue;
      try {
        const response = await fetch("/api/lab-batch-result?run_id=" + encodeURIComponent(run.run_id),
          { cache: "no-store" });
        if (!response.ok) {
          state.batchResults[batch] = { _evidenceUnavailable: true, _runId: String(run.run_id) };
          continue;
        }
        const payload = await response.json();
        const result = payload.result;
        if (!result || result.status !== "SUCCESS") {
          state.batchResults[batch] = { _evidenceUnavailable: true, _runId: String(run.run_id) };
          continue;
        }
        state.batchRunIds[batch] = String(run.run_id);
        state.batchSummaries[batch] = {
          runId: String(run.run_id), url: run.url,
          sourceMonth: run.source_month, result
        };
        state.batchResults[batch] = Object.fromEntries((result.stages || []).map(item =>
          [item.stage, { evidence: item.evidence, url: run.url, runId: String(run.run_id) }]));`;

// Handle CRLF vs LF
const normCode = code.replace(/\r\n/g, '\n');
const normOldHydrate = oldHydrate.replace(/\r\n/g, '\n');
const normNewHydrate = newHydrate.replace(/\r\n/g, '\n');

if (normCode.includes(normOldHydrate)) {
  code = normCode.replace(normOldHydrate, normNewHydrate);
  console.log('3. Replaced hydrateCurrentCycleRuns');
} else {
  console.log('3. oldHydrate not found');
}

// 3. Reset state places
code = code.replace(/state\.batchResults = \{ initial: \{\}, incremental: \{\} \};/g,
  'state.batchResults = Object.fromEntries(["initial", ...Array.from({length: 9}, (_, i) => "incremental_" + String(i + 1).padStart(2, "0"))].map(b => [b, {}]));');
code = code.replace(/state\.batchSummaries = \{ initial: null, incremental: null \};/g,
  'state.batchSummaries = Object.fromEntries(["initial", ...Array.from({length: 9}, (_, i) => "incremental_" + String(i + 1).padStart(2, "0"))].map(b => [b, null]));');
code = code.replace(/state\.batchRunIds = \{ initial: null, incremental: null \};/g,
  'state.batchRunIds = Object.fromEntries(["initial", ...Array.from({length: 9}, (_, i) => "incremental_" + String(i + 1).padStart(2, "0"))].map(b => [b, null]));');

fs.writeFileSync(path, code, 'utf8');
console.log('Done update_app.cjs');
