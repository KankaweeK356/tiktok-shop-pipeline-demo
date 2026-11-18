import test from "node:test";
import assert from "node:assert/strict";
import { simulate, allocateVoucher } from "../../lib/scenario-calc.js";

const target = { revenue_target_thb: 94000, minimum_profit_protection_rate: 0.10, maximum_marketing_gap_rate: 0.30 };
const base = () => ({
  month: "2026-06", target,
  assumptions: { cogs_rate_of_base: 0.40, platform_fee_rate_of_net: 0.10, fulfillment_cost_per_order: 10, affiliate_rate: 0.08,
    affiliate_eligible_share_of_net: 0.5, free_sample_cost: 500, claim_cost: 300 },
  controls: { ads_budget: { PG01: 3000, PG02: 3000, PG03: 3000, PG04: 3000, PG05: 3000 }, voucher: null },
  baskets: [
    { orders: 100, lines: [{ group: "PG01", units: 2, base_price: 199, campaign_unit_price: 189 }, { group: "PG02", units: 1, base_price: 229 }] },
    { orders: 200, lines: [{ group: "PG03", units: 1, base_price: 279 }] },
    { orders: 150, lines: [{ group: "PG04", units: 1, base_price: 189 }, { group: "PG05", units: 1, base_price: 259 }] }]
});

test("SC-01: +1000 Ads with fixed demand lowers profit by exactly 1000 and leaves revenue unchanged", () => {
  const a = simulate(base());
  const more = base(); more.controls.ads_budget.PG01 += 1000;
  const b = simulate(more);
  assert.equal(b.net_revenue, a.net_revenue);
  assert.equal(Math.round((a.contribution_profit - b.contribution_profit) * 100) / 100, 1000);
  assert.equal(a.kind, "WHAT_IF_ASSUMPTIONS_NOT_A_PREDICTION");
});

test("SC-02: voucher is decided per order (threshold, cap, eligibility) and lines sum to the order discount", () => {
  const lines = [{ group: "PG01", afterCampaignCents: 30000 }, { group: "PG02", afterCampaignCents: 20000 }, { group: "PG03", afterCampaignCents: 10000 }];
  const v = { rate: 0.10, min_spend: 400, cap: 40, eligible_groups: ["PG01", "PG02"] };
  const r = allocateVoucher(lines, v);
  assert.equal(r.discount, 4000);                                   // 10% of 500 = 50 -> capped at 40
  assert.equal(r.perLine.reduce((s, x) => s + x, 0), r.discount);
  assert.equal(r.perLine[2], 0);                                    // PG03 not eligible
  assert.equal(allocateVoucher(lines, { ...v, min_spend: 600 }).discount, 0);   // below threshold for the order
  const s = base(); s.controls.voucher = { rate: 0.1, min_spend: 400, cap: 40 };
  assert.equal(simulate(s).voucher_order_check_ok, true);
});

test("SC-03: affiliate cost applies only to the creator-eligible share of Net Revenue", () => {
  const a = simulate(base()), none = base(); none.assumptions.affiliate_eligible_share_of_net = 0;
  const b = simulate(none);
  assert.equal(b.costs.affiliate, 0);
  assert.equal(Math.round(a.costs.affiliate * 100), Math.round(a.net_revenue * 0.5 * 0.08 * 100));
});

test("SC-04: a missing cost input yields INCOMPLETE and never a zero or a PASS", () => {
  for (const key of ["free_sample_cost", "claim_cost", "fulfillment_cost_per_order"]) {
    const s = base(); delete s.assumptions[key];
    const r = simulate(s);
    assert.equal(r.contribution_profit, null); assert.equal(r.profit_status, "INCOMPLETE");
    assert.equal(r.gates.profit_protection.status, "INCOMPLETE"); assert.equal(r.overall, "INCOMPLETE");
    assert.ok(r.unknown_inputs.includes(key));
  }
  const noAds = base(); delete noAds.controls.ads_budget.PG03;
  assert.equal(simulate(noAds).profit_status, "INCOMPLETE");
  const noTarget = simulate({ ...base(), target: null });
  assert.equal(noTarget.gates.revenue.status, "MISSING_TARGET");
});

test("three gates use projected Gross as the denominator and no phantom 60% cost is deducted", () => {
  const r = simulate(base());
  const sum = Object.values(r.costs).reduce((s, x) => s + x, 0);
  assert.equal(Math.round((r.net_revenue - sum) * 100), Math.round(r.contribution_profit * 100));
  assert.equal(r.costs.cogs, Math.round(r.gross * 0.4 * 100) / 100);
  assert.ok(r.gates.profit_protection.rate_pct === Math.round(10000 * r.contribution_profit / r.gross) / 100);
  assert.equal(r.marketing_gap_numerator, Math.round((r.campaign_reduction + r.voucher_discount + r.costs.affiliate + r.costs.ads + r.costs.free_sample) * 100) / 100);
});
