import test from "node:test";
import assert from "node:assert/strict";
import { buildReferencePlan } from "../../lib/scenario-reference.js";
import { simulate } from "../../lib/scenario-calc.js";

const item = (oid, g, q, base, sell, creator, voucher_id = "", net) => ({ oid, g, q, base, sell, creator, voucher_id, net: net ?? q * sell });
// 4 paid orders: O1 (PG01, creator, used V10), O2 (PG01+PG02), O3 (PG05, creator), O4 (PG03)
const items = [item("O1", "PG01", 2, 199, 190, true, "V10", 2 * 190 - 38), item("O2", "PG01", 1, 199, 199, false), item("O2", "PG02", 1, 229, 229, false),
  item("O3", "PG05", 1, 289, 289, true), item("O4", "PG03", 1, 249, 249, false)];
const vouchers = [{ id: "V08", name: "V08", rate: 0.08, min_spend: 150, cap: 30, groups: ["PG01", "PG02", "PG03", "PG04", "PG05"] },
  { id: "V10", name: "V10", rate: 0.10, min_spend: 250, cap: 80, groups: ["PG01", "PG02", "PG05"] }];
const rules = { PG01: 0.06, PG02: 0.08, PG03: 0.10, PG04: 0.12, PG05: 0.09 };
const groupRows = ["PG01", "PG02", "PG03", "PG04", "PG05"].map(g => ({ group_id: g, group_name: g, ads_cost: 1000, profit: 100 }));
const netTotal = items.reduce((s, i) => s + i.net, 0);

test("reference plan: baskets are the real prior orders, scaled to the sealed forecast; rules/vouchers come from Master", () => {
  const r = buildReferencePlan({ items, rules, vouchers, groupRows, shop: { net: netTotal }, officialTotal: netTotal * 2 });
  assert.equal(r.status, "OK"); assert.equal(r.basis.reference_orders, 4); assert.equal(r.basis.scale_factor, 2); assert.equal(r.basis.scaled_orders, 8);
  assert.equal(r.baskets.reduce((s, b) => s + b.orders, 0), 8);
  assert.deepEqual(r.controls.affiliate_rate, rules);                                         // the rule rate, not an average of payouts
  assert.equal(r.groups.PG01.campaign.participating, true); assert.equal(r.groups.PG02.campaign.participating, false);
  assert.equal(r.groups.PG05.affiliate.creator_net_share, 1); assert.equal(r.groups.PG02.affiliate.creator_net_share, 0);
  assert.equal(r.controls.voucher.id, "V10");                                                 // the voucher actually used last month
  const v10 = r.vouchers.find(v => v.id === "V10");
  assert.equal(v10.used_orders, 1); assert.ok(v10.reference_usage_share > 0 && v10.reference_usage_share <= 1);
  assert.equal(r.vouchers.find(v => v.id === "V08").used_orders, 0);
  assert.equal(r.controls.voucher.min_spend, 250);                                           // Master condition, not invented
});

test("plan A reproduces the volume of the official forecast without any demand lift", () => {
  const r = buildReferencePlan({ items, rules, vouchers: [], groupRows, shop: { net: netTotal }, officialTotal: netTotal });
  const out = simulate({ month: "2026-06", baskets: r.baskets, controls: r.controls,
    assumptions: { cogs_rate_of_base: 0.4, platform_fee_rate_of_net: 0.1, fulfillment_cost_per_order: 10, free_sample_cost: 0, claim_cost: 0 }, target: null });
  assert.equal(r.controls.voucher, null);
  assert.ok(Math.abs(out.net_revenue - items.reduce((s, i) => s + i.q * i.sell, 0)) < 0.5);        // same prices, same orders
  assert.equal(out.by_group.PG05.affiliate, Math.round(289 * 0.09 * 100) / 100);                   // creator line only
  assert.equal(out.by_group.PG02.affiliate, 0);
});

test("integrity: no data, unknown group or a basket that does not reconcile to the published month is refused, not guessed", () => {
  assert.equal(buildReferencePlan({ items: [], rules, vouchers, groupRows, shop: { net: 1 }, officialTotal: 1 }).status, "NO_BASKET_DATA");
  assert.equal(buildReferencePlan({ items: [item("O9", "PG99", 1, 1, 1, false)], rules, vouchers, groupRows, shop: { net: 1 }, officialTotal: 1 }).status, "UNKNOWN_GROUP");
  const bad = buildReferencePlan({ items, rules, vouchers, groupRows, shop: { net: netTotal + 500 }, officialTotal: netTotal });
  assert.equal(bad.status, "BASKET_NOT_RECONCILED");
  const noRule = buildReferencePlan({ items, rules: { PG01: 0.06 }, vouchers, groupRows, shop: { net: netTotal }, officialTotal: netTotal });
  assert.equal(noRule.controls.affiliate_rate.PG02, null);                                         // unknown stays null -> INCOMPLETE downstream
});
