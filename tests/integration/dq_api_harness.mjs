// Runs lib/lab-dq.js against a real PostgreSQL (DQ_TEST_DATABASE_URL) through the `pg` package.
// Used only by tests/test_dq_recovery_postgres.py. stdin: {"method","query","body"} -> stdout: {"status","json"}.
import { createRequire } from "node:module";
const requireFromEnv = createRequire(process.env.DQ_TEST_PG_PARENT || import.meta.url);
const pg = requireFromEnv("pg");
const { default: labDQ } = await import("../../lib/lab-dq.js");

const input = JSON.parse(await new Promise(resolve => {
  let data = ""; process.stdin.on("data", c => data += c); process.stdin.on("end", () => resolve(data));
}));
const client = new pg.Client({ connectionString: process.env.DQ_TEST_DATABASE_URL });
await client.connect();
const sql = { query: async (text, params = []) => (await client.query(text, params)).rows };
let status = 200, json = null;
const res = {
  setHeader() {}, status(code) { status = code; return this; }, json(value) { json = value; return this; }
};
const req = { method: input.method, query: input.query || {}, body: input.body, headers: { host: "localhost" } };
await labDQ(req, res, { sql });
await client.end();
process.stdout.write(JSON.stringify({ status, json }));
