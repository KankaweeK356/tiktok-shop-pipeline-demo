/** What-if arithmetic for ONE future month. Pure functions, no I/O, no ML.
 *
 *  Demand (the order baskets) is an explicit ASSUMPTION typed or accepted by the user; nothing here
 *  predicts an incremental effect of marketing. Missing inputs are reported as UNKNOWN / INCOMPLETE,
 *  never coerced to 0. Money is handled in integer satang to keep order-level voucher allocation exact.
 *
 *  Contribution Profit = Net - COGS - Platform fee - Fulfillment - Affiliate - Ads - Sample - Claim
 *  (Campaign reduction and Voucher are already inside Net; the 60% planning envelope is NOT deducted).
 */
export const CALCULATOR_VERSION = "scenario-calc-1";
const GROUPS = ["PG01", "PG02", "PG03", "PG04", "PG05"];
const cents = v => Math.round(Number(v) * 100);
const baht = c => Math.round(c) / 100;
const known = v => v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v));

/** Voucher at ORDER level: eligible lines (after campaign) must reach min spend; discount = min(rate x eligible, cap);
 *  allocated to eligible lines pro rata with the last line balancing so the lines always sum to the order discount. */
export function allocateVoucher(lines, voucher) {
  const out = lines.map(() => 0);
  if (!voucher || !known(voucher.rate) || Number(voucher.rate) <= 0) return { discount: 0, perLine: out };
  const eligibleIdx = lines.map((l, i) => i).filter(i =>
    !voucher.eligible_groups || voucher.eligible_groups.length === 0 || voucher.eligible_groups.includes(lines[i].group));
  const total = eligibleIdx.reduce((s, i) => s + lines[i].afterCampaignCents, 0);
  if (!eligibleIdx.length || total <= 0 || total < cents(voucher.min_spend ?? 0)) return { discount: 0, perLine: out };
  let discount = Math.round(total * Number(voucher.rate));
  if (known(voucher.cap)) discount = Math.min(discount, cents(voucher.cap));
  discount = Math.min(discount, total);
  let remaining = discount;
  eligibleIdx.forEach((i, n) => {
    const share = n === eligibleIdx.length - 1 ? remaining : Math.min(remaining, Math.round(discount * lines[i].afterCampaignCents / total));
    out[i] = share; remaining -= share;
  });
  return { discount, perLine: out };
}

export function simulate({ month, baskets = [], controls = {}, assumptions = {}, target = null }) {
  const unknown = [];
  const need = (name, value) => { if (!known(value)) unknown.push(name); return known(value) ? Number(value) : null; };
  const ads = GROUPS.reduce((s, g) => s + (known(controls.ads_budget?.[g]) ? cents(controls.ads_budget[g]) : 0), 0);
  if (!GROUPS.every(g => known(controls.ads_budget?.[g]))) unknown.push("ads_budget (ต้องระบุครบ 5 กลุ่ม)");
  const cogsRate = need("cogs_rate_of_base", assumptions.cogs_rate_of_base);
  const feeRate = need("platform_fee_rate_of_net", assumptions.platform_fee_rate_of_net);
  const fulfil = need("fulfillment_cost_per_order", assumptions.fulfillment_cost_per_order);
  const affRate = need("affiliate_rate", assumptions.affiliate_rate);
  const affShare = need("affiliate_eligible_share_of_net", assumptions.affiliate_eligible_share_of_net);
  const sample = need("free_sample_cost", assumptions.free_sample_cost);
  const claim = need("claim_cost", assumptions.claim_cost);

  const perGroup = Object.fromEntries(GROUPS.map(g => [g, { gross: 0, campaign: 0, voucher: 0, net: 0 }]));
  let gross = 0, campaign = 0, voucher = 0, orders = 0, voucherChecks = [];
  for (const basket of baskets) {
    const n = Number(basket.orders);
    if (!Number.isInteger(n) || n < 0) throw new Error("BASKET_ORDERS_INVALID");
    const lines = basket.lines.map(l => {
      const grossC = Math.round(Number(l.units) * cents(l.base_price));
      const unitCampaign = known(l.campaign_unit_price) ? cents(l.campaign_unit_price) : cents(l.base_price);
      const afterC = Math.round(Number(l.units) * unitCampaign);
      return { group: l.group, grossCents: grossC, afterCampaignCents: afterC };
    });
    const v = allocateVoucher(lines, controls.voucher);
    voucherChecks.push({ discount: v.discount, lines: v.perLine.reduce((s, x) => s + x, 0) });
    lines.forEach((l, i) => {
      const g = perGroup[l.group]; if (!g) throw new Error("UNKNOWN_GROUP:" + l.group);
      g.gross += n * l.grossCents; g.campaign += n * (l.grossCents - l.afterCampaignCents);
      g.voucher += n * v.perLine[i]; g.net += n * (l.afterCampaignCents - v.perLine[i]);
    });
    orders += n;
  }
  for (const g of Object.values(perGroup)) { gross += g.gross; campaign += g.campaign; voucher += g.voucher; }
  const net = gross - campaign - voucher;
  const complete = unknown.length === 0;
  let profit = null, costs = null;
  if (complete) {
    costs = {
      cogs: Math.round(gross * cogsRate), platform_fee: Math.round(net * feeRate), fulfillment: Math.round(orders * cents(fulfil)),
      affiliate: Math.round(net * affShare * affRate), ads, free_sample: cents(sample), claim: cents(claim)
    };
    profit = net - Object.values(costs).reduce((s, x) => s + x, 0);
  }
  const gapNumerator = complete ? campaign + voucher + costs.affiliate + ads + costs.free_sample : null;
  const gates = {
    revenue: !(target?.revenue_target_thb > 0) ? { status: "MISSING_TARGET" } : {
      status: baht(net) >= target.revenue_target_thb ? "PASS" : "FAIL", target: target.revenue_target_thb,
      gap: baht(net) - target.revenue_target_thb, required_additional_net: Math.max(0, target.revenue_target_thb - baht(net)) },
    profit_protection: !complete || gross <= 0 ? { status: "INCOMPLETE" } : (!known(target?.minimum_profit_protection_rate) ? { status: "MISSING_POLICY" } : {
      status: profit >= Math.round(gross * target.minimum_profit_protection_rate) ? "PASS" : "FAIL",
      rate_pct: Math.round(10000 * profit / gross) / 100, required: baht(Math.round(gross * target.minimum_profit_protection_rate)) }),
    marketing_gap: !complete || gross <= 0 ? { status: "INCOMPLETE" } : (!known(target?.maximum_marketing_gap_rate) ? { status: "MISSING_POLICY" } : {
      status: gapNumerator <= gross * target.maximum_marketing_gap_rate ? "PASS" : "FAIL",
      rate_pct: Math.round(10000 * gapNumerator / gross) / 100, max_rate_pct: Math.round(10000 * target.maximum_marketing_gap_rate) / 100 })
  };
  const statuses = Object.values(gates).map(g => g.status);
  return {
    calculator_version: CALCULATOR_VERSION, month, kind: "WHAT_IF_ASSUMPTIONS_NOT_A_PREDICTION", orders,
    gross: baht(gross), campaign_reduction: baht(campaign), voucher_discount: baht(voucher), net_revenue: baht(net),
    costs: costs && Object.fromEntries(Object.entries(costs).map(([k, v]) => [k, baht(v)])),
    contribution_profit: profit === null ? null : baht(profit), profit_status: complete ? "COMPLETE" : "INCOMPLETE",
    marketing_gap_numerator: gapNumerator === null ? null : baht(gapNumerator),
    by_group: Object.fromEntries(GROUPS.map(g => [g, Object.fromEntries(Object.entries(perGroup[g]).map(([k, v]) => [k, baht(v)]))])),
    gates, unknown_inputs: unknown, voucher_order_check_ok: voucherChecks.every(c => c.discount === c.lines),
    overall: !complete || statuses.includes("INCOMPLETE") ? "INCOMPLETE" :
      statuses.some(s => s.startsWith("MISSING")) ? "INCOMPLETE" : statuses.every(s => s === "PASS") ? "PASS_ASSUMPTIONS" : "FAIL_ASSUMPTIONS",
    note: "ผลคำนวณภายใต้สมมติฐานที่ผู้ใช้ระบุ ไม่ใช่การพยากรณ์ผลของการตลาด และไม่พิสูจน์ว่าแผนจะทำให้ยอดขายเพิ่ม"
  };
}
