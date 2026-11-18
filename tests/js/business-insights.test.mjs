import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// The dashboard file is a classic browser script; evaluate it with a CommonJS-style module object.
const mod = { exports: {} };
new Function("module", readFileSync(new URL("../../dashboard/business-insights.js", import.meta.url), "utf8"))(mod);
const B = mod.exports;

// UAT reference figures from the v4 change request (a fixture only; the app never contains them).
const june = { gross: 114416, net: 104725.06, campaign_reduction: 7281.0, voucher: 2409.94, affiliate: 6560.79, ads: 20016.59, sample: 1230.6, incomplete_rows: 0,
  gates: { revenue: { status: "PASS", achievement_pct: 111.41, gap: 10725.06 } } };

test("marketing frame: allowed = 30% of Gross, actual, overage in baht (v4 UAT-1)", () => {
  const c = B.marketingCap(june, 30);
  assert.equal(c.status, "OVER"); assert.equal(c.allowed, 34324.8); assert.equal(c.actual, 37498.92); assert.equal(c.overage, 3174.12);
  assert.equal(c.rate_pct, 32.77); assert.equal(c.over_pct_points, 2.77); assert.equal(c.top_component.name, "Ads");
});

test("under the frame reports headroom, not an overage; policy cap is an input, not a constant", () => {
  const c = B.marketingCap({ ...june, ads: 5000 }, 30);
  assert.equal(c.status, "WITHIN"); assert.equal(c.overage, 0); assert.ok(c.headroom > 0);
  assert.equal(B.marketingCap(june, 40).status, "WITHIN");
});

test("gross zero, incomplete cost and missing policy are explicit and never PASS or zero", () => {
  assert.equal(B.marketingCap({ ...june, gross: 0 }, 30).status, "NO_GROSS");
  assert.equal(B.marketingCap({ ...june, voucher: null }, 30).status, "INCOMPLETE");
  assert.equal(B.marketingCap({ ...june, incomplete_rows: 2 }, 30).status, "INCOMPLETE");
  assert.equal(B.marketingCap(june, null).status, "NO_POLICY");
});

const group = (id, name, net, gross, profit, extra = {}) => ({ group_id: id, group_name: name, net, gross, profit, cogs: 1, platform_fee: 1, fulfillment: 1, affiliate: 1, sample: 1, claim: 1,
  ads_cost: 1, campaign_reduction: 1, voucher_discount: 1, incomplete_rows: 0, ...extra });

test("group breakdown: missing cost stays null (never 0) and incomplete rows hide profit", () => {
  const b = B.groupBreakdown(group("PG05", "Oversize", 20000.89, 22000, 1553.69));
  assert.equal(b.lines.find(l => l.key === "cogs").value, 1); assert.equal(b.snapshot_has_costs, true);
  const old = B.groupBreakdown({ group_id: "PG05", net: 10, gross: 12, profit: 2 });         // snapshot written before the cost columns existed
  assert.equal(old.snapshot_has_costs, false); assert.equal(old.lines.find(l => l.key === "cogs").missing, true);
  const inc = B.groupBreakdown(group("PG05", "x", 10, 12, 2, { incomplete_rows: 1 }));
  assert.equal(inc.protection_pct, null); assert.equal(inc.lines.find(l => l.key === "profit").missing, true);
});

test("reconciliation flags a mismatch between the five groups and the shop month", () => {
  const rows = [group("PG01", "a", 10, 20, 5), group("PG02", "b", 10, 20, 5)];
  const shop = { gross: 40, net: 20, campaign_reduction: 2, voucher: 2, cogs: 2, platform_fee: 2, fulfillment: 2, affiliate: 2, ads: 2, sample: 2, claim: 2, profit: 10 };
  assert.deepEqual(B.reconcile(rows, shop), []);
  const bad = B.reconcile(rows, { ...shop, cogs: 9 });
  assert.equal(bad.length, 1); assert.equal(bad[0].key, "cogs");
  assert.deepEqual(B.reconcile([{ group_id: "PG01" }], shop), []);                          // nothing to compare when the snapshot lacks the columns
});

test("insights: three measured points that follow the data (PG05 low protection, revenue above target)", () => {
  const groups = [group("PG01", "คอกลม", 1, 22000, 4364.6), group("PG05", "Oversize", 20000.89, 22000, 1553.69)];
  const items = B.insights({ shop: june, groups, maxMarketingPct: 30 });
  assert.equal(items.length, 3);
  assert.match(items[0].title, /เกินกรอบ 3,174\.12 บาท/);
  assert.match(items[1].title, /Oversize มี Profit Protection 7\.06%/); assert.match(items[1].detail, /เกณฑ์อ้างอิง 10%/);
  assert.match(items[2].title, /สูงกว่าเป้า 11\.41%/);
  const calm = B.insights({ shop: { ...june, ads: 5000 }, groups: [group("PG01", "a", 1, 100, 20)], maxMarketingPct: 30 });
  assert.equal(calm[0].tone, "ok"); assert.equal(calm[1].tone, "ok");
  const below = B.insights({ shop: { ...june, gates: { revenue: { achievement_pct: 92.11, gap: -7178.31 } } }, groups: [], maxMarketingPct: 30 });
  assert.match(below[2].title, /ต่ำกว่าเป้า 7\.89%/); assert.equal(below[1].tone, "na");
});
