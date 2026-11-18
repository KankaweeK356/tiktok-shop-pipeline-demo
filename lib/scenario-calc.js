/** What-if arithmetic for ONE future month. Pure functions, no I/O, no ML.
 *
 *  Demand (the order baskets) is an explicit ASSUMPTION typed or accepted by the user; nothing here
 *  predicts an incremental effect of marketing. Missing inputs are reported as UNKNOWN / INCOMPLETE,
 *  never coerced to 0. Money is handled in integer satang to keep order-level voucher allocation exact.
 *
 *  Contribution Profit = Net - COGS - Platform fee - Fulfillment - Affiliate - Ads - Sample - Claim
 *  (Campaign reduction and Voucher are already inside Net; the 60% planning envelope is NOT deducted).
 */
export const CALCULATOR_VERSION = "scenario-calc-2";
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

/** Largest-remainder split of an integer amount so the parts always add up to the total. */
function split(total, weights) {
  const sum = weights.reduce((s, w) => s + w, 0);
  if (!(sum > 0)) return weights.map((_, i) => (i === 0 ? total : 0));
  const raw = weights.map(w => total * w / sum), base = raw.map(Math.floor);
  let left = total - base.reduce((s, x) => s + x, 0);
  raw.map((r, i) => [r - base[i], i]).sort((x, y) => y[0] - x[0]).forEach(([, i]) => { if (left > 0) { base[i] += 1; left -= 1; } });
  return base;
}
const DAYS_IN = month => new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 0)).getUTCDate();

/** Campaign periods inside the planned month must not overlap for the same Product Group.
 *  `periods` = { PG01: [{ from: 1, to: 15, depth_pct: 5 }, ...] } (day-of-month, inclusive). Default is the whole month. */
export function validateCampaignPeriods(month, periods) {
  const days = DAYS_IN(month), depth = {};
  for (const [g, list] of Object.entries(periods || {})) {
    if (!GROUPS.includes(g)) throw new Error("UNKNOWN_GROUP:" + g);
    const sorted = [...list].map(p => ({ from: Number(p.from), to: Number(p.to), depth_pct: Number(p.depth_pct) })).sort((x, y) => x.from - y.from);
    let last = 0, weighted = 0;
    for (const p of sorted) {
      if (![p.from, p.to, p.depth_pct].every(Number.isFinite) || p.from < 1 || p.to > days || p.from > p.to || p.depth_pct < 0 || p.depth_pct > 100) throw new Error("CAMPAIGN_PERIOD_INVALID:" + g);
      if (p.from <= last) throw new Error("CAMPAIGN_PERIOD_OVERLAP:" + g);
      last = p.to; weighted += p.depth_pct * (p.to - p.from + 1);
    }
    depth[g] = Math.round(100 * weighted / days) / 100;         // day-weighted average depth, assuming orders spread evenly over the month
  }
  return depth;
}

const checkRate = (name, v, max = 1) => { if (known(v) && (Number(v) < 0 || Number(v) > max)) throw new Error(name + "_OUT_OF_RANGE"); };

export function simulate({ month, baskets = [], controls = {}, assumptions = {}, target = null }) {
  const unknown = [];
  const need = (name, value) => { if (!known(value)) unknown.push(name); return known(value) ? Number(value) : null; };
  const adsBy = Object.fromEntries(GROUPS.map(g => [g, known(controls.ads_budget?.[g]) ? cents(controls.ads_budget[g]) : 0]));
  if (GROUPS.some(g => known(controls.ads_budget?.[g]) && Number(controls.ads_budget[g]) < 0)) throw new Error("ADS_NEGATIVE");
  const ads = GROUPS.reduce((s, g) => s + adsBy[g], 0);
  if (!GROUPS.every(g => known(controls.ads_budget?.[g]))) unknown.push("ads_budget (ต้องระบุครบ 5 กลุ่ม)");
  const cogsRate = need("cogs_rate_of_base", assumptions.cogs_rate_of_base);
  const feeRate = need("platform_fee_rate_of_net", assumptions.platform_fee_rate_of_net);
  const fulfil = need("fulfillment_cost_per_order", assumptions.fulfillment_cost_per_order);
  const perGroupAffiliate = controls.affiliate_rate && typeof controls.affiliate_rate === "object";
  let affRate = null, affShare = null;
  if (perGroupAffiliate) {
    for (const g of GROUPS) { if (!known(controls.affiliate_rate[g])) unknown.push("affiliate_rate." + g); else checkRate("AFFILIATE_RATE", controls.affiliate_rate[g]); }
  } else { affRate = need("affiliate_rate", assumptions.affiliate_rate); affShare = need("affiliate_eligible_share_of_net", assumptions.affiliate_eligible_share_of_net); }
  const sample = need("free_sample_cost", assumptions.free_sample_cost);
  const claim = need("claim_cost", assumptions.claim_cost);

  // Campaign depth per group (optional override of the basket reference price). Periods default to the whole planned month.
  let depth = controls.campaign_depth_pct ? { ...controls.campaign_depth_pct } : null;
  if (controls.campaign_periods) depth = { ...(depth || {}), ...validateCampaignPeriods(month, controls.campaign_periods) };
  if (depth) for (const v of Object.values(depth)) if (known(v) && (Number(v) < 0 || Number(v) > 100)) throw new Error("CAMPAIGN_DEPTH_OUT_OF_RANGE");
  const usage = known(controls.voucher?.usage_share) ? Number(controls.voucher.usage_share) : 1;
  if (usage < 0 || usage > 1) throw new Error("VOUCHER_USAGE_OUT_OF_RANGE");
  if (controls.voucher) { checkRate("VOUCHER_RATE", controls.voucher.rate); if (known(controls.voucher.cap) && Number(controls.voucher.cap) <= 0) throw new Error("VOUCHER_CAP_INVALID"); }

  const z = () => ({ gross: 0, campaign: 0, voucher: 0, net: 0, affiliate: 0, affiliate_eligible_net: 0, units: 0, orders: 0 });
  const perGroup = Object.fromEntries(GROUPS.map(g => [g, z()]));
  let orders = 0, voucherChecks = [], fulfilByGroup = Object.fromEntries(GROUPS.map(g => [g, 0]));
  for (const basket of baskets) {
    const n = Number(basket.orders);
    if (!Number.isInteger(n) || n < 0) throw new Error("BASKET_ORDERS_INVALID");
    const lines = basket.lines.map(l => {
      const grossC = Math.round(Number(l.units) * cents(l.base_price));
      const d = depth && known(depth[l.group]) ? Number(depth[l.group]) : null;
      const unitCampaign = d !== null ? Math.round(cents(l.base_price) * (1 - d / 100)) : (known(l.campaign_unit_price) ? cents(l.campaign_unit_price) : cents(l.base_price));
      return { group: l.group, units: Number(l.units), grossCents: grossC, afterCampaignCents: Math.round(Number(l.units) * unitCampaign), creator: l.creator === true };
    });
    const raw = allocateVoucher(lines, controls.voucher);
    let perLine = raw.perLine, discount = raw.discount;
    if (usage < 1 && discount > 0) {                          // only a share of the eligible orders actually use a voucher (assumption)
      const scaled = Math.round(discount * usage);
      perLine = split(scaled, raw.perLine); discount = scaled;
    }
    voucherChecks.push({ discount, lines: perLine.reduce((s, x) => s + x, 0) });
    const basketGross = lines.reduce((s, l) => s + l.grossCents, 0);
    lines.forEach((l, i) => {
      const g = perGroup[l.group]; if (!g) throw new Error("UNKNOWN_GROUP:" + l.group);
      const netLine = l.afterCampaignCents - perLine[i];
      g.gross += n * l.grossCents; g.campaign += n * (l.grossCents - l.afterCampaignCents); g.voucher += n * perLine[i]; g.net += n * netLine;
      g.units += n * l.units; g.orders += n;
      if (perGroupAffiliate && l.creator && known(controls.affiliate_rate[l.group])) {
        g.affiliate_eligible_net += n * netLine; g.affiliate += n * Math.round(netLine * Number(controls.affiliate_rate[l.group]));
      }
      if (basketGross > 0) fulfilByGroup[l.group] += n * (l.grossCents / basketGross);            // order-level cost spread by gross share
    });
    orders += n;
  }
  const sum = k => GROUPS.reduce((s, g) => s + perGroup[g][k], 0);
  const gross = sum("gross"), campaign = sum("campaign"), voucher = sum("voucher"), net = gross - campaign - voucher;
  const complete = unknown.length === 0;
  let profit = null, costs = null, groupCosts = null;
  const grossW = GROUPS.map(g => perGroup[g].gross), netW = GROUPS.map(g => perGroup[g].net);
  if (complete) {
    const totalAffiliate = perGroupAffiliate ? sum("affiliate") : Math.round(net * affShare * affRate);
    costs = { cogs: Math.round(gross * cogsRate), platform_fee: Math.round(net * feeRate), fulfillment: Math.round(orders * cents(fulfil)),
      affiliate: totalAffiliate, ads, free_sample: cents(sample), claim: cents(claim) };
    profit = net - Object.values(costs).reduce((s, x) => s + x, 0);
    const byW = (total, w) => split(total, w);
    const cg = byW(costs.cogs, grossW), pf = byW(costs.platform_fee, netW), fu = byW(costs.fulfillment, GROUPS.map(g => fulfilByGroup[g])),
      af = perGroupAffiliate ? GROUPS.map(g => perGroup[g].affiliate) : byW(costs.affiliate, netW), sm = byW(costs.free_sample, grossW), cl = byW(costs.claim, grossW);
    groupCosts = Object.fromEntries(GROUPS.map((g, i) => [g, { cogs: cg[i], platform_fee: pf[i], fulfillment: fu[i], affiliate: af[i], ads: adsBy[g], free_sample: sm[i], claim: cl[i] }]));
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
      rate_pct: Math.round(10000 * gapNumerator / gross) / 100, max_rate_pct: Math.round(10000 * target.maximum_marketing_gap_rate) / 100,
      allowed: baht(Math.round(gross * target.maximum_marketing_gap_rate)), actual: baht(gapNumerator),
      overage: baht(Math.max(0, gapNumerator - Math.round(gross * target.maximum_marketing_gap_rate))) })
  };
  const statuses = Object.values(gates).map(g => g.status);
  const byGroup = Object.fromEntries(GROUPS.map(g => {
    const p = perGroup[g], c = groupCosts?.[g];
    const gp = c ? p.net - c.cogs - c.platform_fee - c.fulfillment - c.affiliate - c.ads - c.free_sample - c.claim : null;
    return [g, { gross: baht(p.gross), campaign: baht(p.campaign), voucher: baht(p.voucher), net: baht(p.net), orders: p.orders,
      ...(c ? Object.fromEntries(Object.entries(c).map(([k, v]) => [k, baht(v)])) : {}), profit: gp === null ? null : baht(gp),
      protection_pct: gp === null || p.gross <= 0 ? null : Math.round(10000 * gp / p.gross) / 100,
      affiliate_eligible_net: perGroupAffiliate ? baht(p.affiliate_eligible_net) : null }];
  }));
  return {
    calculator_version: CALCULATOR_VERSION, month, kind: "WHAT_IF_ASSUMPTIONS_NOT_A_PREDICTION", orders,
    gross: baht(gross), campaign_reduction: baht(campaign), voucher_discount: baht(voucher), net_revenue: baht(net),
    costs: costs && Object.fromEntries(Object.entries(costs).map(([k, v]) => [k, baht(v)])),
    contribution_profit: profit === null ? null : baht(profit), profit_status: complete ? "COMPLETE" : "INCOMPLETE",
    marketing_gap_numerator: gapNumerator === null ? null : baht(gapNumerator),
    by_group: byGroup,
    gates, unknown_inputs: unknown, voucher_order_check_ok: voucherChecks.every(c => c.discount === c.lines),
    overall: !complete || statuses.includes("INCOMPLETE") ? "INCOMPLETE" :
      statuses.some(s => s.startsWith("MISSING")) ? "INCOMPLETE" : statuses.every(s => s === "PASS") ? "PASS_ASSUMPTIONS" : "FAIL_ASSUMPTIONS",
    note: "ผลคำนวณภายใต้สมมติฐานที่ผู้ใช้ระบุ ไม่ใช่การพยากรณ์ผลของการตลาด และไม่พิสูจน์ว่าแผนจะทำให้ยอดขายเพิ่ม"
  };
}
