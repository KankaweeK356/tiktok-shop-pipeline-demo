/** Reference plan for the what-if, derived ONLY from the previous PUBLISHED month (ER1 orders that reconcile to the Published ER2)
 *  and the Master/rule tables. Pure function: the SQL lives in lib/lab-forecast.js. Nothing is typed in the browser.
 *
 *  - baskets   = the previous month's real paid orders (lines with group, units, list price, creator flag), counts scaled so the
 *                total net lines up with the sealed Official Forecast (a volume ASSUMPTION, not an ML prediction).
 *  - ads       = previous month's Ads per group (Published ER2)
 *  - campaign  = previous month's average campaign depth per group (price reduction / gross)
 *  - affiliate = rule rate per group (Ref_Affiliate_Commission_Rule effective in the target month)
 *  - vouchers  = Dim_Voucher + Bridge (rate, minimum spend, cap, eligible groups) and the share of eligible orders that used each one
 */
import { createHash } from "node:crypto";
import { allocateVoucher } from "./scenario-calc.js";

export const GROUPS = ["PG01", "PG02", "PG03", "PG04", "PG05"];
const cents = v => Math.round(Number(v) * 100);
const r2 = v => Math.round(v * 100) / 100;
const r4 = v => Math.round(v * 10000) / 10000;

export function buildReferencePlan({ items, rules, vouchers, groupRows, shop, officialTotal, groupNames = {} }) {
  if (!items.length) return { status: "NO_BASKET_DATA" };
  const orders = new Map();
  for (const it of items) {
    if (!GROUPS.includes(it.g)) return { status: "UNKNOWN_GROUP", group: it.g };
    if (!orders.has(it.oid)) orders.set(it.oid, { voucher_id: it.voucher_id || "", lines: [] });
    orders.get(it.oid).lines.push({ group: it.g, units: Number(it.q), base_price: Number(it.base), campaign_unit_price: Number(it.sell), creator: Boolean(it.creator) });
  }
  const netTotal = items.reduce((s, it) => s + Number(it.net), 0);
  if (shop && Number.isFinite(Number(shop.net)) && Math.abs(netTotal - Number(shop.net)) > 1)
    return { status: "BASKET_NOT_RECONCILED", basket_net: r2(netTotal), published_net: Number(shop.net) };

  const stat = Object.fromEntries(GROUPS.map(g => [g, { gross: 0, after: 0, net: 0, creator_net: 0, items: 0 }]));
  for (const it of items) {
    const s = stat[it.g]; s.gross += it.q * it.base; s.after += it.q * it.sell; s.net += Number(it.net); s.items += 1;
    if (it.creator) s.creator_net += Number(it.net);
  }
  // distinct basket shapes with their (unscaled) order counts
  const shapes = new Map();
  for (const [, o] of orders) {
    const lines = [...o.lines].sort((a, b) => (a.group + a.base_price + a.units + a.creator).localeCompare(b.group + b.base_price + b.units + b.creator));
    const key = JSON.stringify(lines.map(l => [l.group, l.units, l.base_price, l.campaign_unit_price, l.creator]));
    const e = shapes.get(key) || { lines, count: 0, voucher_ids: [] };
    e.count += 1; e.voucher_ids.push(o.voucher_id); shapes.set(key, e);
  }
  const refOrders = orders.size;
  const k = netTotal > 0 && officialTotal > 0 ? officialTotal / netTotal : 1;
  const scaledTotal = Math.round(refOrders * k);
  let baskets = [...shapes.values()].map(e => ({ orders: Math.round(e.count * k), lines: e.lines }));
  const drift = scaledTotal - baskets.reduce((s, b) => s + b.orders, 0);
  if (drift !== 0) { const big = baskets.reduce((m, b) => (b.orders > m.orders ? b : m), baskets[0]); big.orders = Math.max(0, big.orders + drift); }
  baskets = baskets.filter(b => b.orders > 0);

  // vouchers: eligibility is tested on the REAL baskets with the Master rule; usage share = used / eligible (capped at 1)
  const voucherList = vouchers.map(v => {
    const rule = { rate: Number(v.rate), min_spend: Number(v.min_spend || 0), cap: v.cap === null || v.cap === undefined ? null : Number(v.cap), eligible_groups: v.groups };
    let eligible = 0, used = 0;
    for (const [, o] of orders) {
      const lines = o.lines.map(l => ({ group: l.group, afterCampaignCents: Math.round(l.units * cents(l.campaign_unit_price)) }));
      if (allocateVoucher(lines, rule).discount > 0) { eligible += 1; if (o.voucher_id === v.id) used += 1; }
    }
    return { id: v.id, name: v.name || v.id, rate: rule.rate, min_spend: rule.min_spend, cap: rule.cap, eligible_groups: v.groups,
      reference_usage_share: eligible > 0 ? r4(Math.min(1, used / eligible)) : 0, eligible_orders: eligible, used_orders: used };
  });
  const mostUsed = [...voucherList].sort((a, b) => b.used_orders - a.used_orders)[0];
  const refVoucher = mostUsed && mostUsed.used_orders > 0 ? mostUsed : null;

  const groups = Object.fromEntries(GROUPS.map(g => {
    const s = stat[g], row = groupRows.find(r => r.group_id === g) || {}, rule = rules[g];
    const depth = s.gross > 0 ? r2(100 * (1 - s.after / s.gross)) : 0;
    return [g, { name: groupNames[g] || row.group_name || g, ads_reference: r2(Number(row.ads_cost || 0)),
      campaign: { participating: depth > 0, depth_pct_reference: depth },
      affiliate: { rule_rate: rule === undefined ? null : Number(rule), creator_net_share: s.net > 0 ? r4(s.creator_net / s.net) : null },
      prior: { net: r2(s.net), gross: r2(s.gross), profit: row.profit === null || row.profit === undefined ? null : Number(row.profit),
        protection_pct: row.profit === null || row.profit === undefined || !s.gross ? null : r2(100 * Number(row.profit) / s.gross) } }];
  }));
  const controls = {
    ads_budget: Object.fromEntries(GROUPS.map(g => [g, groups[g].ads_reference])),
    campaign_depth_pct: Object.fromEntries(GROUPS.map(g => [g, groups[g].campaign.participating ? groups[g].campaign.depth_pct_reference : 0])),
    affiliate_rate: Object.fromEntries(GROUPS.map(g => [g, groups[g].affiliate.rule_rate])),
    voucher: refVoucher ? { id: refVoucher.id, rate: refVoucher.rate, min_spend: refVoucher.min_spend, cap: refVoucher.cap,
      eligible_groups: refVoucher.eligible_groups, usage_share: refVoucher.reference_usage_share, custom: false } : null };
  const hash = createHash("sha256").update(JSON.stringify(baskets)).digest("hex").slice(0, 16);
  return { status: "OK", groups, vouchers: voucherList, controls, baskets, basket_hash: hash,
    basis: { reference_orders: refOrders, reference_net: r2(netTotal), scale_factor: r4(k), scaled_orders: scaledTotal, official_total: r2(officialTotal || 0) } };
}
