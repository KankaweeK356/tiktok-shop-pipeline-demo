import test from "node:test";
import assert from "node:assert/strict";
import labDQ, { safeParent, sameOrigin, CORRECT_SQL } from "../../lib/lab-dq.js";

const ISSUE = "11111111-1111-4111-8111-111111111111";
function call({ method = "GET", query = {}, body = null, headers = {}, rows = [] }) {
  const calls = [];
  const sql = { query: async (text, params) => { calls.push({ text, params }); const next = rows.shift(); return next ?? []; } };
  let status = 200, json = null;
  const res = { setHeader() {}, status(c) { status = c; return this; }, json(v) { json = v; return this; } };
  return labDQ({ method, query, body, headers: { host: "app.test", ...headers } }, res, { sql })
    .then(() => ({ status, json, calls }));
}
const issueRow = { issue_id: ISSUE, parent_table: "Dim_SKU", parent_column: "SKU_ID", row_snapshot: {}, status: "OPEN" };
const good = { issue_id: ISSUE, corrected_value: "PG01-BL-M", actor: "owner", reason: "Confirmed from the order slip",
  evidence_ref: "SLIP-1", expected_version: 0, idempotency_key: "key-12345678" };

test("identifiers come only from the Source contract", () => {
  assert.deepEqual(safeParent({ parent_table: "Dim_SKU", parent_column: "SKU_ID" }), { table: "Dim_SKU", column: "SKU_ID" });
  assert.equal(safeParent({ parent_table: 'Dim_SKU"; DROP TABLE x;--', parent_column: "SKU_ID" }), null);
  assert.equal(safeParent({ parent_table: "pg_user", parent_column: "usename" }), null);
  assert.equal(safeParent({ parent_table: "Dim_SKU", parent_column: "NoSuchColumn" }), null);
  assert.match(CORRECT_SQL("Dim_SKU", "SKU_ID"), /demo_er1\."Dim_SKU" WHERE "SKU_ID"=\$3/);
});

test("cross-site writes are refused", async () => {
  assert.equal(sameOrigin({ headers: { "sec-fetch-site": "cross-site" } }), false);
  assert.equal(sameOrigin({ headers: { origin: "https://evil.test", host: "app.test" } }), false);
  const r = await call({ method: "POST", query: { dq: "correct" }, body: good, headers: { "sec-fetch-site": "cross-site" } });
  assert.equal(r.status, 403); assert.equal(r.calls.length, 0);
});

test("a correction without actor, reason or evidence never reaches the database", async () => {
  for (const patch of [{ actor: "" }, { reason: "short" }, { evidence_ref: "" }, { corrected_value: "" },
                       { idempotency_key: "x" }, { expected_version: -1 }, { issue_id: "nope" }]) {
    const r = await call({ method: "POST", query: { dq: "correct" }, body: { ...good, ...patch } });
    assert.equal(r.status, 400, JSON.stringify(patch));
    assert.equal(r.calls.length, 0);
  }
});

test("value outside the master is rejected with 422 and a conflicting version with 409", async () => {
  const notInMaster = await call({ method: "POST", query: { dq: "correct" }, body: good,
    rows: [[issueRow], [{ issue_found: 1, current_version: 0, master_ok: 0, inserted: null, replay: null }]] });
  assert.equal(notInMaster.status, 422); assert.equal(notInMaster.json.error_code, "VALUE_NOT_IN_MASTER");
  const conflict = await call({ method: "POST", query: { dq: "correct" }, body: good,
    rows: [[issueRow], [{ issue_found: 1, current_version: 2, master_ok: 1, inserted: null, replay: null }]] });
  assert.equal(conflict.status, 409); assert.equal(conflict.json.error_code, "VERSION_CONFLICT");
  const created = await call({ method: "POST", query: { dq: "correct" }, body: good,
    rows: [[issueRow], [{ issue_found: 1, current_version: 0, master_ok: 1, inserted: { version: 1, correction_id: "c" }, replay: null }]] });
  assert.equal(created.status, 201); assert.equal(created.json.version, 1);
});

test("revalidate is refused while an issue has no correction and unknown ops are rejected", async () => {
  process.env.CLASSROOM_LAB_ADMIN_KEY = "k";
  const run = { run_id: "r", status: "BLOCKED_DQ", cycle_number: 1, result_summary: { batch: "incremental_02" } };
  const r = await call({ method: "POST", query: { dq: "revalidate" }, body: { actor: "owner" },
    rows: [[run], [{ open_count: 1, total: 1 }]] });
  assert.equal(r.status, 409); assert.equal(r.json.error_code, "ISSUES_UNCORRECTED");
  assert.equal((await call({ query: { dq: "drop_everything" } })).status, 400);
});
