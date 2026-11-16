/**
 * Test HTTP handlers directly as Vercel Serverless Functions
 */
import assert from "node:assert";
import labBatchHandler from "../api/lab-batch.js";
import labResultHandler from "../api/lab-batch-result.js";
import labResetHandler from "../api/lab-reset.js";

// Mock Request & Response objects
function createMockReq(method = "GET", query = {}, body = null) {
  return {
    method,
    query,
    headers: { "content-type": "application/json" },
    body,
    async *[Symbol.asyncIterator]() {
      if (body) {
        yield Buffer.from(typeof body === "string" ? body : JSON.stringify(body));
      }
    }
  };
}

function createMockRes() {
  const res = {
    statusCode: 200,
    headers: {},
    body: null,
    setHeader(k, v) { res.headers[k] = v; return res; },
    status(code) { res.statusCode = code; return res; },
    json(data) { res.body = data; return res; },
    send(data) { res.body = data; return res; }
  };
  return res;
}

async function runApiTests() {
  console.log("=== TESTING API ENDPOINTS DIRECTLY ===\n");

  // 1. GET /api/lab-batch
  console.log("1. Test GET /api/lab-batch");
  const req1 = createMockReq("GET");
  const res1 = createMockRes();
  await labBatchHandler(req1, res1);
  assert.strictEqual(res1.statusCode, 200);
  assert.ok(res1.body.ready);
  assert.strictEqual(res1.body.months.length, 10);
  console.log("✓ GET /api/lab-batch returned 10 months status successfully.\n");

  // 2. POST /api/lab-batch (run_next)
  console.log("2. Test POST /api/lab-batch { action: 'run_next' }");
  const req2 = createMockReq("POST", {}, { action: "run_next" });
  const res2 = createMockRes();
  await labBatchHandler(req2, res2);
  assert.strictEqual(res2.statusCode, 200);
  assert.ok(res2.body.success);
  console.log("✓ POST /api/lab-batch executed single stage successfully.\n");

  // 3. GET /api/lab-batch-result?business=1
  console.log("3. Test GET /api/lab-batch-result?business=1");
  const req3 = createMockReq("GET", { business: "1" });
  const res3 = createMockRes();
  await labResultHandler(req3, res3);
  assert.strictEqual(res3.statusCode, 200);
  assert.ok(Array.isArray(res3.body.months));
  assert.ok(Array.isArray(res3.body.groups));
  console.log("✓ GET /api/lab-batch-result?business=1 returned published warehouse financials.\n");

  // 4. GET /api/lab-batch-result?ml=1
  console.log("4. Test GET /api/lab-batch-result?ml=1");
  const req4 = createMockReq("GET", { ml: "1" });
  const res4 = createMockRes();
  await labResultHandler(req4, res4);
  assert.strictEqual(res4.statusCode, 200);
  assert.ok("ready" in res4.body);
  console.log("✓ GET /api/lab-batch-result?ml=1 returned ML evaluation response:", res4.body.status);

  console.log("\n=== ALL API FUNCTION TESTS PASSED 100% ===");
}

runApiTests().catch(err => {
  console.error("API test failed:", err);
  process.exit(1);
});
