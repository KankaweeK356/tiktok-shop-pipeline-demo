/** Pure helpers for the Business Actual tab (no DOM). Every figure comes from the Published ER2 rows passed in;
 *  nothing here knows a month, a group or an amount. Money is compared in integer satang. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.BusinessInsights = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const known = v => v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v));
  const cents = v => Math.round(Number(v) * 100);
  const baht = c => c / 100;

  /** Marketing cost frame: allowed = gross x policy cap; overage = max(actual - allowed, 0). Nothing is defaulted to zero. */
  function marketingCap(shop, maxRatePct) {
    const parts = [shop?.ads, shop?.campaign_reduction, shop?.affiliate, shop?.voucher, shop?.sample];
    if (!known(maxRatePct)) return { status: "NO_POLICY" };
    if (!shop || parts.some(p => !known(p)) || shop.incomplete_rows > 0) return { status: "INCOMPLETE" };
    if (!known(shop.gross) || Number(shop.gross) <= 0) return { status: "NO_GROSS" };
    const actual = parts.reduce((s, p) => s + cents(p), 0), gross = cents(shop.gross);
    const allowed = Math.round(gross * Number(maxRatePct) / 100);
    const diff = actual - allowed;
    const shares = { Ads: cents(shop.ads), Campaign: cents(shop.campaign_reduction), Affiliate: cents(shop.affiliate), Voucher: cents(shop.voucher), "Free Sample": cents(shop.sample) };
    const top = Object.entries(shares).sort((a, b) => b[1] - a[1])[0];
    return { status: diff > 0 ? "OVER" : "WITHIN", allowed: baht(allowed), actual: baht(actual), overage: baht(Math.max(diff, 0)), headroom: baht(Math.max(-diff, 0)),
      rate_pct: Math.round(10000 * actual / gross) / 100, over_pct_points: Math.round(10000 * diff / gross) / 100, max_rate_pct: Number(maxRatePct),
      top_component: actual > 0 ? { name: top[0], share_pct: Math.round(1000 * top[1] / actual) / 10 } : null };
  }

  const LINES = [["gross", "Gross Reference Sales", "gross", false], ["campaign_reduction", "− ส่วนลด Campaign", "cost", false], ["voucher_discount", "− Voucher", "cost", false],
    ["net", "= Net Revenue", "net", true], ["cogs", "− COGS", "cost", false], ["platform_fee", "− Platform Fee", "cost", false], ["fulfillment", "− Fulfillment", "cost", false],
    ["affiliate", "− Affiliate", "cost", false], ["ads_cost", "− Ads", "cost", false], ["sample", "− Free Sample", "cost", false], ["claim", "− Claim", "cost", false],
    ["profit", "= กำไร (Profit)", "profit", true]];

  /** Ordered breakdown lines for one group-month row. A missing/incomplete value is returned as null (shown as "ข้อมูลไม่ครบ"), never 0. */
  function groupBreakdown(row) {
    const incomplete = Number(row?.incomplete_rows) > 0;
    const lines = LINES.map(([key, label, kind, total]) => {
      let value = known(row?.[key]) ? Number(row[key]) : null;
      if (incomplete && (key === "profit")) value = null;
      return { key, label, kind, total, value, missing: value === null };
    });
    const gross = known(row?.gross) ? Number(row.gross) : null, profit = lines.find(l => l.key === "profit").value;
    return { lines, incomplete, protection_pct: gross && gross > 0 && profit !== null ? Math.round(10000 * profit / gross) / 100 : null,
      snapshot_has_costs: ["cogs", "platform_fee", "fulfillment", "affiliate", "sample", "claim"].every(k => known(row?.[k])) };
  }

  /** Sum of the five groups must equal the shop-month for every cost line (same mart grain). Returns the mismatches. */
  function reconcile(groupRows, shop) {
    const out = [];
    for (const [key, label] of [["gross", "Gross"], ["net", "Net"], ["campaign_reduction", "Campaign"], ["voucher_discount", "Voucher"], ["cogs", "COGS"], ["platform_fee", "Platform"],
      ["fulfillment", "Fulfillment"], ["affiliate", "Affiliate"], ["ads_cost", "Ads"], ["sample", "Sample"], ["claim", "Claim"], ["profit", "Profit"]]) {
      const shopKey = { voucher_discount: "voucher", ads_cost: "ads" }[key] || key;
      if (!groupRows.length || groupRows.some(r => !known(r[key])) || !known(shop?.[shopKey])) continue;      // cannot compare what is missing
      const sum = groupRows.reduce((s, r) => s + cents(r[key]), 0), total = cents(shop[shopKey]);
      if (Math.abs(sum - total) > 5) out.push({ key, label, groups: baht(sum), shop: baht(total) });         // 5 satang rounding tolerance
    }
    return out;
  }

  /** Three measured points only; no causal claims. `labels` = { next: "กรกฎาคม" | null, name(groupId, row) }. */
  function insights({ shop, groups, maxMarketingPct, minProtectionPct = 10 }) {
    const cap = marketingCap(shop, maxMarketingPct), items = [];
    if (cap.status === "OVER") items.push({ tone: "warn", key: "marketing", over: cap.overage,
      title: `ค่าใช้จ่ายการตลาดเกินกรอบ ${fmt(cap.overage)} บาท`,
      detail: `ควรตรวจว่า Ads, Campaign, Affiliate และ Voucher ส่วนใดมีสัดส่วนสูง โดยดูรายละเอียดประกอบก่อนลดงบ${cap.top_component ? ` (ส่วนที่สูงสุดคือ ${cap.top_component.name} ${cap.top_component.share_pct}% ของค่าใช้จ่ายการตลาด)` : ""}` });
    else if (cap.status === "WITHIN") items.push({ tone: "ok", key: "marketing", title: `ค่าใช้จ่ายการตลาดต่ำกว่ากรอบ ${fmt(cap.headroom)} บาท`,
      detail: `ใช้ ${fmt(cap.rate_pct)}% ของ Gross จากกรอบ ${fmt(cap.max_rate_pct)}%` });
    else items.push({ tone: "na", key: "marketing", title: "ยังสรุปสัดส่วนต้นทุนการตลาดไม่ได้",
      detail: { INCOMPLETE: "ข้อมูลค่าใช้จ่ายการตลาดไม่ครบ ไม่นับเป็นผ่าน", NO_GROSS: "ไม่สามารถคำนวณสัดส่วนต้นทุนการตลาดได้ เพราะ Gross เป็นศูนย์", NO_POLICY: "ไม่มีเพดานจากนโยบายแผน" }[cap.status] });
    const rated = (groups || []).map(g => ({ g, p: groupBreakdown(g).protection_pct })).filter(x => x.p !== null).sort((a, b) => a.p - b.p);
    if (!rated.length) items.push({ tone: "na", key: "groups", title: "ยังไม่มีข้อมูลกำไรรายกลุ่ม", detail: "ข้อมูลต้นทุนรายกลุ่มไม่ครบใน Snapshot นี้" });
    else if (rated[0].p < minProtectionPct) {
      const low = rated.filter(x => x.p < minProtectionPct);
      items.push({ tone: "warn", key: "groups", group_ids: low.map(x => x.g.group_id), title: `${groupLabel(rated[0].g)} มีอัตรากำไร ${fmt(rated[0].p)}%`,
        detail: `ต่ำกว่าเกณฑ์อ้างอิง ${minProtectionPct}% ควรตรวจต้นทุนและส่วนลดของกลุ่มนี้เพิ่มเติม${low.length > 1 ? ` (กลุ่มที่ต่ำกว่าเกณฑ์: ${low.map(x => x.g.group_id).join(", ")})` : ""} · เกณฑ์ ${minProtectionPct}% เป็นเกณฑ์ระดับร้าน ใช้เป็นข้อมูลอ้างอิงรายกลุ่มเท่านั้น` });
    } else items.push({ tone: "ok", key: "groups", title: `ทุกกลุ่มมีอัตรากำไรไม่ต่ำกว่า ${minProtectionPct}%`, detail: `ต่ำสุดคือ ${groupLabel(rated[0].g)} ${fmt(rated[0].p)}%` });
    const ach = shop?.gates?.revenue;
    if (ach && ach.achievement_pct !== null && ach.achievement_pct !== undefined) {
      const delta = Math.round((ach.achievement_pct - 100) * 100) / 100;
      items.push(delta >= 0 ? { tone: "ok", key: "revenue", title: `ยอดขายสุทธิทั้งร้านสูงกว่าเป้า ${fmt(delta)}%`, detail: "ควรรักษายอดขายควบคู่กับการควบคุมค่าใช้จ่าย ไม่เน้นลดงบอย่างเดียว" }
        : { tone: "warn", key: "revenue", title: `ยอดขายสุทธิทั้งร้านต่ำกว่าเป้า ${fmt(-delta)}%`, detail: `ขาดจากเป้า ${fmt(Math.abs(ach.gap))} บาท ควรตรวจกลุ่มสินค้าที่ยอดต่ำก่อนวางแผน` });
    } else items.push({ tone: "na", key: "revenue", title: "ไม่มีเป้ายอดขายของเดือนนี้", detail: "เทียบกับเป้าไม่ได้ (MISSING_TARGET)" });
    return items;
  }
  const fmt = n => Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const groupLabel = g => (g.group_name ? g.group_name : g.group_id);
  return { marketingCap, groupBreakdown, reconcile, insights, LINES };
});
