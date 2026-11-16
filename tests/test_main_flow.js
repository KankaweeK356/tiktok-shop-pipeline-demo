/**
 * Automated Main Flow & Data Quality Test Suite
 * Tests:
 * 1. Stepwise Isolation: Run Next Step executes January Stage 1 ONLY
 * 2. Generic DQ Assertion: Halts on March SKU_ERR_UNKNOWN_DEMO
 * 3. Generalization Test: Generic FK rule flags arbitrary unseen SKU
 * 4. Human Fix Workflow: Audit logging, packing slip evidence, revalidation
 * 5. Full 10-Month Orchestration & Business Target Reconciliation
 */
import assert from "node:assert";
import { 
  executeSingleStage, 
  getPipelineStatus, 
  submitCorrection, 
  resetDemoState, 
  getPublishedBusinessData, 
  DELIVERIES, 
  STAGES, 
  MONTHLY_METRICS 
} from "../lib/etl-engine.js";

async function runTests() {
  console.log("=== STARTING TIKTOK SHOP PIPELINE DEMO TESTS ===\n");

  // TEST 1: Reset & Verify Clean State
  console.log("TEST 1: Reset to Clean State");
  resetDemoState();
  let status = getPipelineStatus();
  assert.strictEqual(status.active_batch, "initial", "Active batch must be initial (Jan)");
  assert.strictEqual(status.published_count, 0, "Published count must be 0");
  assert.strictEqual(status.next_stage, "ingest", "Next stage must be ingest");
  console.log("✓ Lab reset verified. Initial batch is January (initial), next stage is ingest.\n");

  // TEST 2: Isolation Test - Run Next Step on Clean Lab executes Stage 1 ONLY
  console.log("TEST 2: Stepwise Isolation Test (Run Next Step executes January Stage 1 ONLY)");
  const janStage1 = await executeSingleStage("initial", "ingest");
  assert.strictEqual(janStage1.success, true, "Stage 1 must succeed");
  assert.strictEqual(janStage1.stage, "ingest", "Executed stage must be ingest");
  
  status = getPipelineStatus();
  assert.strictEqual(status.published_count, 0, "January must NOT be published yet after Stage 1");
  assert.strictEqual(status.next_stage, "extract", "Next stage must now be extract (Stage 2)");
  
  // Verify stages 2-5 have not executed
  const janMonth = status.months.find(m => m.month === "2026-01");
  assert.strictEqual(janMonth.stages[0].status, "completed", "Stage 1 must be completed");
  assert.strictEqual(janMonth.stages[1].status, "ready", "Stage 2 must be ready");
  assert.strictEqual(janMonth.stages[2].status, "pending", "Stage 3 must be pending");
  assert.strictEqual(janMonth.stages[3].status, "pending", "Stage 4 must be pending");
  assert.strictEqual(janMonth.stages[4].status, "pending", "Stage 5 must be pending");
  console.log("✓ Isolation verified: January Stage 1 executed, Stages 2-5 have no output.\n");

  // TEST 3: Finish January (Stages 2-5)
  console.log("TEST 3: Finish January Stages 2-5");
  for (const s of ["extract", "transform", "load", "validate"]) {
    const res = await executeSingleStage("initial", s);
    assert.strictEqual(res.success, true, `Stage ${s} must succeed`);
  }
  status = getPipelineStatus();
  assert.strictEqual(status.published_count, 1, "January must be PUBLISHED");
  assert.strictEqual(status.active_batch, "incremental_01", "Pointer must advance to Feb (incremental_01)");
  assert.strictEqual(status.next_stage, "ingest", "Feb next stage must be ingest");
  console.log("✓ January successfully published. Active batch advanced to February.\n");

  // TEST 4: Execute February (Stages 1-5)
  console.log("TEST 4: Execute February (Incremental Load)");
  for (const s of STAGES) {
    const res = await executeSingleStage("incremental_01", s);
    assert.strictEqual(res.success, true, `Feb stage ${s} must succeed`);
  }
  status = getPipelineStatus();
  assert.strictEqual(status.published_count, 2, "February must be PUBLISHED");
  assert.strictEqual(status.active_batch, "incremental_02", "Pointer must advance to March (incremental_02)");
  console.log("✓ February successfully published. Active batch advanced to March.\n");

  // TEST 5: March Stage 1 - Generic Foreign Key Detection must halt on SKU_ERR_UNKNOWN_DEMO
  console.log("TEST 5: March Generic Foreign Key Check (Detection of SKU_ERR_UNKNOWN_DEMO)");
  const marchStage1 = await executeSingleStage("incremental_02", "ingest");
  assert.strictEqual(marchStage1.success, false, "March Stage 1 must FAIL on invalid SKU");
  assert.strictEqual(marchStage1.error_code, "FOREIGN_KEY_VIOLATION", "Error code must be FOREIGN_KEY_VIOLATION");
  assert.strictEqual(marchStage1.failed_rule, "SKU_REFERENCE_EXISTS", "Rule must be generic SKU_REFERENCE_EXISTS");
  
  status = getPipelineStatus();
  assert.strictEqual(status.is_blocked, true, "Pipeline must be BLOCKED");
  assert.strictEqual(status.published_count, 2, "Jan and Feb must remain PUBLISHED without corruption");
  assert.strictEqual(status.next_stage, null, "Next stage must be null while blocked");
  console.log("✓ Generic FK check successfully halted execution on SKU_ERR_UNKNOWN_DEMO without corrupting Jan/Feb.\n");

  // TEST 6: Negative / Generalization Test - Arbitrary unseen invalid SKU
  console.log("TEST 6: Negative Generalization Test (Arbitrary unseen SKU)");
  const testPatchUnseen = { "ORD-202603-00001-I1": "SKU_NOVEL_TEST_99" };
  const unseenResult = await executeSingleStage("incremental_02", "ingest", { overridePatch: testPatchUnseen });
  // Since SKU_NOVEL_TEST_99 is not in Dim_SKU, it must STILL fail under the generic rule
  assert.strictEqual(unseenResult.success, false, "Generic rule must reject novel unknown SKU");
  assert.strictEqual(status.published_count, 2, "Jan and Feb must STILL remain PUBLISHED");
  console.log("✓ Negative generalization verified: generic FK validation rejects arbitrary unknown SKUs.\n");

  // TEST 7: Human Data Correction Workflow
  console.log("TEST 7: Human Data Correction Workflow");
  // Submit fix based on packing slip evidence (คอกลม สีดำ ไซส์ L -> PG01-BL-L)
  const fixSubmission = submitCorrection({
    order_item_id: "ORD-202603-00001-I1",
    corrected_sku: "PG01-BL-L",
    actor: "Senior QA / Data Owner",
    reason: "ยืนยันจากใบเสร็จคำสั่งซื้อและ Packing Slip คลังสินค้า: เสื้อยืดคอกลม สีดำ ไซส์ L (199 THB)"
  });
  assert.strictEqual(fixSubmission.success, true, "Fix submission must succeed");
  assert.strictEqual(fixSubmission.audit.corrected_sku, "PG01-BL-L");
  assert.ok(fixSubmission.audit.checksum, "Audit checksum must be generated");
  console.log("✓ Correction registered with immutable audit log and checksum:", fixSubmission.audit.checksum.slice(0, 16));

  // Re-run March Stage 1 with the approved fix
  console.log("TEST 8: Revalidate March Stage 1 with Approved Fix");
  const marchRevalidated = await executeSingleStage("incremental_02", "ingest");
  assert.strictEqual(marchRevalidated.success, true, "March Stage 1 must pass after approved fix");
  console.log("✓ March Stage 1 revalidated successfully.\n");

  // Finish March Stages 2-5
  for (const s of ["extract", "transform", "load", "validate"]) {
    const res = await executeSingleStage("incremental_02", s);
    assert.strictEqual(res.success, true, `March stage ${s} must succeed`);
  }
  status = getPipelineStatus();
  assert.strictEqual(status.published_count, 3, "March must be PUBLISHED");
  console.log("✓ March successfully published. Active batch is April.\n");

  // TEST 9: Complete Remaining Months (Apr-Oct)
  console.log("TEST 9: Complete Remaining Months (Apr–Oct)");
  for (let idx = 3; idx < DELIVERIES.length; idx++) {
    const batch = DELIVERIES[idx];
    const month = MONTHLY_METRICS[Object.keys(MONTHLY_METRICS)[idx]].month;
    for (const s of STAGES) {
      const res = await executeSingleStage(batch, s);
      assert.strictEqual(res.success, true, `${month} stage ${s} must succeed`);
    }
  }

  status = getPipelineStatus();
  assert.strictEqual(status.published_count, 10, "All 10 months must be PUBLISHED");
  assert.strictEqual(status.is_completed, true, "Pipeline is_completed must be true");
  console.log("✓ All 10 monthly deliveries executed and published end-to-end.\n");

  // TEST 10: Financial & Business KPI Reconciliation Matrix
  console.log("TEST 10: Financial & Business KPI Acceptance Reconciliation");
  const bizData = getPublishedBusinessData();
  assert.strictEqual(bizData.months.length, 10, "Must have 10 published business months");

  const expectedStatuses = [
    { month: "2026-01", target: "PASS", profit: "PASS" },
    { month: "2026-02", target: "FAIL", profit: "PASS" },
    { month: "2026-03", target: "PASS", profit: "PASS" },
    { month: "2026-04", target: "PASS", profit: "FAIL" },
    { month: "2026-05", target: "FAIL", profit: "FAIL" },
    { month: "2026-06", target: "PASS", profit: "PASS" },
    { month: "2026-07", target: "FAIL", profit: "PASS" },
    { month: "2026-08", target: "PASS", profit: "FAIL" },
    { month: "2026-09", target: "PASS", profit: "PASS" },
    { month: "2026-10", target: "PASS", profit: "PASS" }
  ];

  expectedStatuses.forEach(exp => {
    const act = bizData.months.find(m => m.month === exp.month);
    assert.ok(act, `Month ${exp.month} must exist in published data`);
    assert.strictEqual(act.target_status, exp.target, `${exp.month} target status must be ${exp.target}`);
    assert.strictEqual(act.profit_protection_status, exp.profit, `${exp.month} profit status must be ${exp.profit}`);
    
    // Verify profit protection formula: Profit >= 10% of Gross Reference Sales
    const requiredProfit = act.gross_reference_sales * 0.10;
    if (exp.profit === "PASS") {
      assert.ok(act.contribution_profit >= requiredProfit, `${exp.month} profit must >= 10% gross`);
    } else {
      assert.ok(act.contribution_profit < requiredProfit, `${exp.month} profit must < 10% gross`);
    }

    console.log(`  ${exp.month} -> Target: ${act.target_status} (${act.revenue_achievement_pct}%), Profit Protection: ${act.profit_protection_status} (${act.profit_protection_rate_pct}% vs 10%) [MATCH]`);
  });

  console.log("\n=== ALL 10 UNIT & INTEGRATION TESTS PASSED 100% ===");

  // TEST 11: Fresh Run All Test (Starts from completely clean state without prior Run Next Step)
  console.log("\nTEST 11: Fresh Run All Test (Start from clean state, auto-run until March error)");
  resetDemoState();
  status = getPipelineStatus();
  assert.strictEqual(status.published_count, 0, "Must start with 0 published months");
  assert.strictEqual(status.active_batch, "initial", "Must start at initial batch");

  // Simulate Run All client orchestrator loop
  let loopCount = 0;
  while (!status.is_completed && !status.is_blocked && loopCount < 50) {
    loopCount++;
    const res = await executeSingleStage(status.active_batch, status.next_stage);
    status = getPipelineStatus();
    if (!res.success) break;
  }

  assert.strictEqual(status.is_blocked, true, "Fresh Run All must automatically stop when it hits March Stage 1 DQ failure");
  assert.strictEqual(status.active_batch, "incremental_02", "Must be at March (incremental_02)");
  assert.strictEqual(status.published_count, 2, "Jan and Feb must have been published automatically");
  console.log(`✓ Fresh Run All executed Jan and Feb (${loopCount} stage calls) and automatically paused at March Stage 1.`);

  console.log("\n=== ALL 11 MAIN FLOW ACCEPTANCE TESTS COMPLETED SUCCESSFULLY ===");
}

runTests().catch(err => {
  console.error("Test failed:", err);
  process.exit(1);
});
