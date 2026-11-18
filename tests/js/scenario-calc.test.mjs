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

// ---- v2: per Product Group controls (Scenario Planning v5) ------------------------------------------------------
import { validateCampaignPeriods } from "../../lib/scenario-calc.js";
const v2 = () => {
  const s = base();
  s.assumptions = { cogs_rate_of_base: 0.40, platform_fee_rate_of_net: 0.10, fulfillment_cost_per_order: 10, free_sample_cost: 500, claim_cost: 300 };
  s.controls = { ads_budget: { PG01: 3000, PG02: 3000, PG03: 3000, PG04: 3000, PG05: 3000 }, voucher: null,
    affiliate_rate: { PG01: 0.06, PG02: 0.08, PG03: 0.10, PG04: 0.12, PG05: 0.09 } };
  s.baskets = [
    { orders: 100, lines: [{ group: "PG01", units: 2, base_price: 199, creator: true }, { group: "PG02", units: 1, base_price: 229, creator: false }] },
    { orders: 200, lines: [{ group: "PG03", units: 1, base_price: 279, creator: true }] },
    { orders: 150, lines: [{ group: "PG04", units: 1, base_price: 189, creator: false }, { group: "PG05", units: 1, base_price: 259, creator: true }] }];
  return s;
};
const sumGroups = (r, k) => Math.round(Object.values(r.by_group).reduce((s, g) => s + g[k], 0) * 100) / 100;

test("S-05: affiliate is charged only on creator lines, at the group rate, on net after voucher", () => {
  const r = simulate(v2());
  const expected = 100 * Math.round(2 * 19900 * 0.06) + 200 * Math.round(27900 * 0.10) + 150 * Math.round(25900 * 0.09);
  assert.equal(Math.round(r.costs.affiliate * 100), expected);
  assert.equal(r.by_group.PG02.affiliate, 0); assert.equal(r.by_group.PG04.affiliate, 0);            // no creator line -> no commission
  const up = v2(); up.controls.affiliate_rate.PG04 = 0.30;                                           // PG04 has no creator lines
  assert.equal(simulate(up).costs.affiliate, r.costs.affiliate);
  const pg3 = v2(); pg3.controls.affiliate_rate.PG03 = 0.20;
  assert.ok(simulate(pg3).costs.affiliate > r.costs.affiliate);
});

test("S-06: campaign depth is per group; non-participating groups keep the reference price; overlap is rejected", () => {
  const none = simulate(v2()), s = v2(); s.controls.campaign_depth_pct = { PG03: 10 };
  const r = simulate(s);
  assert.equal(r.by_group.PG03.campaign, Math.round(200 * 27900 * 0.10) / 100);
  assert.equal(r.by_group.PG01.campaign, none.by_group.PG01.campaign);
  assert.ok(r.net_revenue < none.net_revenue);
  assert.throws(() => validateCampaignPeriods("2026-06", { PG01: [{ from: 1, to: 15, depth_pct: 5 }, { from: 10, to: 30, depth_pct: 8 }] }), /CAMPAIGN_PERIOD_OVERLAP:PG01/);
  assert.throws(() => validateCampaignPeriods("2026-06", { PG01: [{ from: 1, to: 31, depth_pct: 5 }] }), /CAMPAIGN_PERIOD_INVALID/);       // June has 30 days
  const weighted = validateCampaignPeriods("2026-06", { PG02: [{ from: 1, to: 15, depth_pct: 10 }] });
  assert.equal(weighted.PG02, 5);                                                                    // half the month at 10% -> 5% average
});

test("S-07: voucher limited to PG05 only discounts qualifying baskets, one voucher per order, with min spend / cap / usage share", () => {
  const s = v2(); s.controls.voucher = { rate: 0.10, min_spend: 200, cap: 20, eligible_groups: ["PG05"] };
  const r = simulate(s);
  assert.equal(r.by_group.PG05.voucher, 150 * 20);                  // 10% of 259 = 25.9 -> capped at 20 per order, 150 orders
  for (const g of ["PG01", "PG02", "PG03", "PG04"]) assert.equal(r.by_group[g].voucher, 0);
  assert.equal(r.voucher_order_check_ok, true);
  s.controls.voucher.usage_share = 0.5;
  assert.equal(simulate(s).by_group.PG05.voucher, 150 * 20 * 0.5);  // only half of eligible orders use it
  s.controls.voucher.min_spend = 300;
  assert.equal(simulate(s).by_group.PG05.voucher, 0);               // basket below the threshold
});

test("S-04/S-14: group Ads move only that group and the shop total; group results reconcile to the shop", () => {
  const a = simulate(v2()), s = v2(); s.controls.ads_budget.PG05 += 1000;
  const b = simulate(s);
  assert.equal(Math.round((a.contribution_profit - b.contribution_profit) * 100) / 100, 1000);
  assert.equal(b.by_group.PG05.ads, a.by_group.PG05.ads + 1000); assert.equal(b.by_group.PG01.ads, a.by_group.PG01.ads);
  assert.equal(b.net_revenue, a.net_revenue);                                                         // no automatic demand lift
  for (const key of ["gross", "campaign", "voucher", "net", "cogs", "platform_fee", "fulfillment", "affiliate", "ads", "free_sample", "claim", "profit"])
    assert.equal(sumGroups(a, key), key === "campaign" ? a.campaign_reduction : key === "voucher" ? a.voucher_discount : key === "net" ? a.net_revenue :
      key === "profit" ? a.contribution_profit : key === "gross" ? a.gross : a.costs[key === "free_sample" ? "free_sample" : key], key);
});

test("S-09: a missing affiliate rate or out-of-range input is INCOMPLETE / rejected, never silently zero", () => {
  const s = v2(); delete s.controls.affiliate_rate.PG02;
  const r = simulate(s);
  assert.equal(r.profit_status, "INCOMPLETE"); assert.ok(r.unknown_inputs.includes("affiliate_rate.PG02")); assert.equal(r.by_group.PG01.profit, null);
  const bad = v2(); bad.controls.affiliate_rate.PG01 = 1.5;
  assert.throws(() => simulate(bad), /AFFILIATE_RATE_OUT_OF_RANGE/);
  const neg = v2(); neg.controls.ads_budget.PG01 = -5;
  assert.throws(() => simulate(neg), /ADS_NEGATIVE/);
});
