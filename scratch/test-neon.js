import { getNeonSql } from "../lib/neon-router.js";

async function main() {
  const sql = getNeonSql("live");
  try {
    const state = await sql.query("SELECT * FROM demo_control.dataset_state");
    console.log("dataset_state:", JSON.stringify(state, null, 2));
  } catch (e) {
    console.error("dataset_state err:", e.message);
  }
  try {
    const runs = await sql.query("SELECT run_id, dataset_key, cycle_number, run_type, status, started_at, finished_at FROM demo_control.pipeline_runs ORDER BY started_at DESC LIMIT 5");
    console.log("pipeline_runs:", JSON.stringify(runs, null, 2));
  } catch (e) {
    console.error("pipeline_runs err:", e.message);
  }
  try {
    const orders = await sql.query('SELECT count(*)::int AS n FROM demo_er1."Fact_Orders"');
    console.log("Fact_Orders count:", JSON.stringify(orders, null, 2));
  } catch (e) {
    console.error("Fact_Orders err:", e.message);
  }
}

main();
