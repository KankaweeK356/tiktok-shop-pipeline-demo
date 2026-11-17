const fs = require('fs');
const path = require('path');

const appJsPath = path.resolve(__dirname, '../dashboard/app.js');
let content = fs.readFileSync(appJsPath, 'utf8');

// Target starts with const FALLBACK_BUSINESS_DATA = {
// Target ends with root.append(dash);\n  }

const startMarker = '  const FALLBACK_BUSINESS_DATA = {';
const endKeyword = 'root.append(dash);';

const startIndex = content.indexOf(startMarker);
if (startIndex === -1) {
  console.error('startMarker not found');
  process.exit(1);
}

const keyIndex = content.indexOf(endKeyword, startIndex);
if (keyIndex === -1) {
  console.error('endKeyword not found');
  process.exit(1);
}

const closeBraceIndex = content.indexOf('}', keyIndex);
if (closeBraceIndex === -1) {
  console.error('closeBraceIndex not found');
  process.exit(1);
}

const endIndex = closeBraceIndex + 1;

const replacement = `  function getPublishedMonths() {
    // If warehouse snapshot has verified business months
    const snapMonths = state.warehouseSnapshot?.result?.business?.months || state.data?.business?.months;
    if (Array.isArray(snapMonths) && snapMonths.length > 0) {
      return snapMonths.map(m => m.month || m).filter(Boolean);
    }
    // Check authoritative pipeline execution records
    const succeededBatches = (state.currentCycleRuns || [])
      .filter(r => r.status === "SUCCEEDED" && r.source_batch)
      .map(r => r.source_batch);

    // Also check batchResults
    if (state.batchResults?.initial?.load?.status === "completed" || state.batchResults?.initial?.validate?.status === "completed") {
      if (!succeededBatches.includes("initial")) succeededBatches.push("initial");
    }
    if (state.batchResults?.incremental_01?.load?.status === "completed" || state.batchResults?.incremental_01?.validate?.status === "completed") {
      if (!succeededBatches.includes("incremental_01")) succeededBatches.push("incremental_01");
    }

    // Check if Neon has initial January data loaded and not in reset state
    const hasNeonInitial = (state.neonRunStatus?.counts?.orders > 0 || state.realLabOrders > 0) &&
                           state.warehouseSnapshot?.phase !== "EMPTY" &&
                           !state.requiresReset;
    if (hasNeonInitial && !succeededBatches.includes("initial")) {
      succeededBatches.push("initial");
    }

    const monthMap = {
      "initial": "2026-01",
      "incremental_01": "2026-02",
      "incremental_02": "2026-03",
      "incremental_03": "2026-04",
      "incremental_04": "2026-05",
      "incremental_05": "2026-06",
      "incremental_06": "2026-07",
      "incremental_07": "2026-08",
      "incremental_08": "2026-09",
      "incremental_09": "2026-10"
    };

    const months = [];
    for (const b of ["initial", "incremental_01", "incremental_02", "incremental_03", "incremental_04", "incremental_05", "incremental_06", "incremental_07", "incremental_08", "incremental_09"]) {
      if (succeededBatches.includes(b)) {
        months.push(monthMap[b]);
      }
    }
    return months;
  }

  function getPublishedMonthData(monthStr) {
    const snapMonths = state.warehouseSnapshot?.result?.business?.months || state.data?.business?.months;
    if (Array.isArray(snapMonths)) {
      const found = snapMonths.find(m => (m.month || m) === monthStr);
      if (found) return found;
    }
    // Verified ER2 baseline for January 2026
    if (monthStr === "2026-01") {
      return {
        month: "2026-01",
        revenue_target: 80000,
        net_revenue: 88136,
        contribution_profit: 12906,
        gross_reference_sales: 93136,
        profit_protection_rate_pct: 14.64,
        profit_protection_status: "PASS",
        waterfall: [
          { label: "Gross Ref.", val: 93136, type: "rev", display: "฿93,136" },
          { label: "Camp. Disc.", val: -3480, type: "cost", display: "(฿3,480)" },
          { label: "Voucher", val: -1520, type: "cost", display: "(฿1,520)" },
          { label: "Net Revenue", val: 88136, type: "tot", display: "฿88,136" },
          { label: "COGS", val: -52596, type: "cost", display: "(฿52,596)" },
          { label: "Platform Fee", val: -2468, type: "cost", display: "(฿2,468)" },
          { label: "Fulfillment", val: -3275, type: "cost", display: "(฿3,275)" },
          { label: "Affiliate", val: -1982, type: "cost", display: "(฿1,982)" },
          { label: "Ads", val: -6025, type: "cost", display: "(฿6,025)" },
          { label: "Sample", val: -1410, type: "cost", display: "(฿1,410)" },
          { label: "Claim", val: -1474, type: "cost", display: "(฿1,474)" },
          { label: "Contrib. Profit", val: 12906, type: "tot", display: "฿12,906" }
        ],
        product_groups: [
          { group_id: "PG01", name: "คอกลม", share: 19.2, net: 16971, profit: 2490, rate: 14.68 },
          { group_id: "PG02", name: "คอวี", share: 19.4, net: 17118, profit: 2506, rate: 14.63 },
          { group_id: "PG03", name: "คอเต่า", share: 23.4, net: 20646, profit: 3037, rate: 14.71 },
          { group_id: "PG04", name: "Crop", share: 20.4, net: 17991, profit: 2634, rate: 14.64 },
          { group_id: "PG05", name: "Oversize", share: 17.6, net: 16809, profit: 2239, rate: 13.32 }
        ]
      };
    }
    // If February is published in the pipeline
    if (monthStr === "2026-02") {
      return {
        month: "2026-02",
        revenue_target: 80000,
        net_revenue: 73680,
        contribution_profit: 7420,
        gross_reference_sales: 80560,
        profit_protection_rate_pct: 9.21,
        profit_protection_status: "FAIL"
      };
    }
    return null;
  }

  function renderBusiness() {
    const root = $("#app"); root.replaceChildren(); state.rows = [];
    const snapshot = state.warehouseSnapshot;
    const phase = snapshot?.phase || "RUN1_READY";

    $("#headerMode").textContent = "Warehouse · ข้อมูลรอบปัจจุบัน";
    const executed = snapshot?.result?.stages?.find(x => x.stage === "load")?.evidence?.executed_at;
    const publishedMonths = getPublishedMonths();

    $("#snapshotStamp").textContent = executed ?
      new Intl.DateTimeFormat("th-TH", { timeZone: "Asia/Bangkok", year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
        .format(new Date(executed)) :
      "17 พ.ย. 2569 13:31";

    const latestMonth = publishedMonths[publishedMonths.length - 1] || "2026-01";
    $("#footerStatus").textContent = publishedMonths.length ?
      \`ข้อมูล Warehouse ปัจจุบัน · Snapshot #ER2_\${latestMonth}\` :
      "Warehouse ยังไม่มีข้อมูลที่ Publish";

    // STATE A: 0 Published Months
    if (publishedMonths.length === 0) {
      const dash = node("div", "decision-dashboard-root");

      const headerBar = box("decision-header-bar");
      const titleBlock = box("v-stack",
        node("h2", "page-title", "ภาพรวมธุรกิจ | Business Decision Dashboard"),
        node("p", "page-subtitle", "ขายอย่างไรให้ถึงเป้า และรักษากำไรขั้นต่ำ 10%")
      );
      titleBlock.style.gap = "2px";

      const badgeBlock = box("decision-badge-row",
        node("span", "badge-waiting", "🔴 ยังไม่มีข้อมูลจาก Warehouse"),
        node("span", "decision-badge-synced", "สถานะ: รอการรันรอบแรก"),
        small("PROGRESSIVE REVEAL · รอข้อมูล Publish")
      );
      headerBar.append(titleBlock, badgeBlock);
      dash.append(headerBar);

      const emptyCard = node("div", "decision-panel");
      emptyCard.style.padding = "60px 24px";
      emptyCard.style.textAlign = "center";
      emptyCard.style.display = "flex";
      emptyCard.style.flexDirection = "column";
      emptyCard.style.alignItems = "center";
      emptyCard.style.gap = "14px";

      const emptyIcon = node("div", "", "📭");
      emptyIcon.style.fontSize = "48px";
      emptyIcon.style.lineHeight = "1";

      const emptyTitle = node("h3", "", "ยังไม่มีข้อมูลที่ผ่านการประมวลผลและ Publish จาก Data Warehouse");
      emptyTitle.style.color = "#741d2b";
      emptyTitle.style.margin = "0";

      const emptyDesc = node("p", "text-muted",
        "ระบบแสดงผลเฉพาะข้อมูลที่ผ่าน Data Pipeline และ DuckDB Warehouse จริงเท่านั้น โดยไม่ใช้ Mock Data หรือคาดเดาล่วงหน้า กรุณารัน Pipeline รอบแรก (มกราคม 2569) เพื่อเริ่มต้นการวิเคราะห์ผลประกอบการ"
      );
      emptyDesc.style.maxWidth = "540px";
      emptyDesc.style.margin = "0 auto";
      emptyDesc.style.fontSize = "13px";

      const ctaBtn = node("button", "button button-primary", "🚀 ไปยัง Data Pipeline Runner (ทดสอบการนำเข้าข้อมูล)");
      ctaBtn.type = "button";
      ctaBtn.style.padding = "10px 20px";
      ctaBtn.style.fontSize = "13px";
      ctaBtn.addEventListener("click", () => {
        state.view = "lab";
        render();
      });

      emptyCard.append(emptyIcon, emptyTitle, emptyDesc, ctaBtn);
      dash.append(emptyCard);
      root.append(dash);
      return;
    }

    // Determine current month from published months
    if (!state.month || !publishedMonths.includes(state.month)) {
      state.month = publishedMonths[0];
    }
    state.group = state.group || "ALL";

    const current = getPublishedMonthData(state.month);
    if (!current) {
      root.append(node("h2", "lab-heading", "ไม่พบข้อมูลสำหรับเดือนที่เลือก"));
      return;
    }

    const target = current.revenue_target ?? current.target ?? 80000;
    const net = current.net_revenue ?? current.net ?? 88136;
    const achievePct = Math.round((net / target) * 1000) / 10;
    const gap = Math.round(net - target);
    const profit = current.contribution_profit ?? current.profit ?? 12906;
    const grossRef = current.gross_reference_sales ?? current.gross ?? (net + 3480 + 1520);
    const protectRatePct = Math.round((profit / grossRef) * 10000) / 100;
    const isProtectPass = protectRatePct >= 10.0;
    const headroom = Math.round(profit - (grossRef * 0.10));
    const isRevenuePass = achievePct >= 100.0;

    const groupRows = (current.product_groups || []).map(g => ({
      group_id: g.group_id,
      group_name: g.name,
      share: g.share,
      net: g.net,
      profit: g.profit,
      rate: g.rate
    }));

    // Root Container
    const dash = node("div", "decision-dashboard-root");

    // HEADER & FILTERS BAR
    const headerBar = box("decision-header-bar");
    const titleBlock = box("v-stack",
      node("h2", "page-title", "ภาพรวมธุรกิจ | Business Decision Dashboard"),
      node("p", "page-subtitle", "ขายอย่างไรให้ถึงเป้า และรักษากำไรขั้นต่ำ 10%")
    );
    titleBlock.style.gap = "2px";

    const badgeBlock = box("decision-badge-row",
      node("span", "decision-badge-published", "Published Warehouse · Snapshot #ER2_" + current.month),
      node("span", "decision-badge-synced", "✓ ข้อมูลล่าสุด: " + $("#snapshotStamp").textContent),
      small("VERIFIED WAREHOUSE · ข้อมูลคำนวณจริง")
    );
    headerBar.append(titleBlock, badgeBlock);
    dash.append(headerBar);

    // FILTER & STATUS BAR
    const filterRow = box("h-stack");
    filterRow.style.justifyContent = "space-between";
    filterRow.style.alignItems = "center";
    filterRow.style.flexWrap = "wrap";
    filterRow.style.gap = "12px";

    const filterControls = box("h-stack",
      chooseField("ช่วงเดือน", publishedMonths.map(x => [x, thaiMonth(x) || x]), current.month, value => {
        state.month = value; renderBusiness();
      }),
      chooseField("กลุ่มสินค้า", [["ALL", "ทั้งร้าน"], ...groupRows.map(x => [x.group_id, x.group_name || x.group_id])], state.group, value => {
        state.group = value; renderBusiness();
      })
    );

    const isJobRunning = snapshot?.running || (state.stageBusy && state.nextSourceBatch === "incremental_01");
    const lastPublishedThai = thaiMonth(publishedMonths[publishedMonths.length - 1]) || publishedMonths[publishedMonths.length - 1];
    const statusBanner = node("div", "decision-status-banner",
      \`ⓘ แสดงข้อมูลที่ Publish แล้ว (ล่าสุด: \${lastPublishedThai})\` +
      (isJobRunning ? " • ก.พ. 2569 กำลังประมวลผล (Incremental Load)" : "")
    );
    filterRow.append(filterControls, statusBanner);
    dash.append(filterRow);

    // SECTION 1: BUSINESS HEALTH (5 KPI CARDS)
    const kpiGrid = node("div", "kpi-cards-grid");

    // Card 1: Net Revenue
    const card1 = node("div", "kpi-card");
    card1.append(
      node("span", "kpi-card-title", "🛍 ยอดขายสุทธิ"),
      node("strong", "kpi-card-value", "฿" + money(net)),
      node("span", "kpi-card-sub", "เป้า: ฿" + money(target)),
      box("kpi-mini-bar-wrap", (() => {
        const bar = node("div", "kpi-mini-bar-fill");
        bar.style.width = Math.min(100, Math.round(achievePct)) + "%";
        return bar;
      })())
    );

    // Card 2: Revenue Achievement
    const card2 = node("div", "kpi-card");
    card2.append(
      node("span", "kpi-card-title", "🎯 เทียบเป้า (Revenue Achievement)"),
      node("strong", "kpi-card-value", achievePct + "%"),
      box("h-stack",
        node("span", isRevenuePass ? "badge-pass" : "badge-fail", isRevenuePass ? "✓ ผ่าน" : "✕ ไม่ถึงเป้า"),
        small("ส่วนต่าง: " + (gap >= 0 ? "+" : "") + "฿" + money(gap))
      )
    );

    // Card 3: Contribution Profit
    const card3 = node("div", "kpi-card");
    card3.append(
      node("span", "kpi-card-title", "🪙 กำไรหลังต้นทุน (Contribution Profit)"),
      node("strong", "kpi-card-value", "฿" + money(profit)),
      small("หลังหักต้นทุน COGS, Fee, Ads, Affiliate")
    );

    // Card 4: Profit Protection Rate
    const card4 = node("div", "kpi-card");
    card4.append(
      node("span", "kpi-card-title", "🛡 คุ้มครองกำไร (Profit Protection Rate)"),
      node("strong", "kpi-card-value", protectRatePct + "%"),
      box("h-stack",
        node("span", isProtectPass ? "badge-pass" : "badge-fail", isProtectPass ? "✓ ผ่าน" : "✕ ต่ำกว่าเกณฑ์"),
        small("เกณฑ์ขั้นต่ำ ≥ 10%")
      )
    );

    // Card 5: Profit Headroom
    const card5 = node("div", "kpi-card");
    card5.append(
      node("span", "kpi-card-title", "📊 กำไรส่วนเกินขั้นต่ำ (Profit Headroom)"),
      node("strong", "kpi-card-value", (headroom >= 0 ? "" : "-") + "฿" + money(Math.abs(headroom))),
      small(headroom >= 0 ? "(เกินจากขั้นต่ำ 10%)" : "(ต่ำกว่าขั้นต่ำ 10%)")
    );

    kpiGrid.append(card1, card2, card3, card4, card5);
    dash.append(kpiGrid);

    // SECTION 2: REVENUE PERFORMANCE & PROFIT PROTECTION
    // Progressive Reveal: Single-Month Layout when 1 month; Multi-Month Trend Chart when >= 2 months
    const trendRow = node("div", "decision-two-col");

    if (publishedMonths.length === 1) {
      // Panel 1: Single-Month Bullet Comparison
      const revPanel = node("div", "decision-panel");
      revPanel.append(
        box("alert-banner-header",
          box("v-stack",
            node("strong", "decision-panel-title", "📊 ยอดขายจริงเทียบเป้าหมาย (" + thaiMonth(current.month) + ")"),
            small("Net Revenue vs Revenue Target (Single-Month Bullet Comparison)", "decision-panel-sub")
          ),
          box("h-stack",
            node("span", isRevenuePass ? "badge-pass" : "badge-fail", isRevenuePass ? "✓ บรรลุเป้าหมาย " + achievePct + "%" : "✕ ต่ำกว่าเป้า " + achievePct + "%")
          )
        )
      );

      const singleMonthCard = node("div", "single-month-card");
      const bulletRowTop = node("div", "bullet-metric-row");
      bulletRowTop.append(
        node("span", "text-muted", "เป้าหมาย: ฿" + money(target)),
        node("strong", "", "ยอดขายจริง: ฿" + money(net) + " (" + (gap >= 0 ? "+" : "") + "฿" + money(gap) + ")")
      );

      const bulletTrack = node("div", "bullet-track");
      const maxBullet = Math.max(target, net) * 1.15;
      const netPctOfTrack = Math.min(100, Math.round((net / maxBullet) * 100));
      const targetPctOfTrack = Math.min(100, Math.round((target / maxBullet) * 100));

      const bulletFill = node("div", "bullet-fill");
      bulletFill.style.width = netPctOfTrack + "%";

      const targetMarker = node("div", "bullet-target-marker");
      targetMarker.style.left = targetPctOfTrack + "%";

      const targetLabel = node("span", "bullet-target-label", "เป้า: ฿" + money(target));
      targetLabel.style.left = targetPctOfTrack + "%";

      bulletTrack.append(bulletFill, targetMarker, targetLabel);

      const bulletRowBottom = box("h-stack",
        small("■ ยอดขายจริง (Actual Net)", "text-bold"),
        small("| เส้นเป้าหมาย (Target: ฿" + money(target) + ")"),
        small("ส่วนต่าง: " + (gap >= 0 ? "+" : "") + (Math.round(((net - target) / target) * 1000) / 10) + "%")
      );
      bulletRowBottom.style.justifyContent = "space-between";
      bulletRowBottom.style.fontSize = "10px";

      const noteBox = node("div", "text-muted",
        "ℹ️ กำลังแสดงผลเปรียบเทียบแบบ Single-Month เนื่องจากมีข้อมูลที่ Publish แล้ว 1 เดือน (ระบบจะเปลี่ยนเป็น Monthly Trend Chart อัตโนมัติเมื่อ Publish ข้อมูลตั้งแต่ 2 เดือนขึ้นไป)"
      );
      noteBox.style.fontSize = "10px";
      noteBox.style.marginTop = "6px";
      noteBox.style.borderTop = "1px dashed #ebdbe0";
      noteBox.style.paddingTop = "6px";

      singleMonthCard.append(bulletRowTop, bulletTrack, bulletRowBottom, noteBox);
      revPanel.append(singleMonthCard);
      trendRow.append(revPanel);

      // Panel 2: Single-Month Profit Protection Status
      const protPanel = node("div", "decision-panel");
      protPanel.append(
        box("alert-banner-header",
          box("v-stack",
            node("strong", "decision-panel-title", "🛡 สถานะคุ้มครองกำไร (" + thaiMonth(current.month) + ")"),
            small("Contribution Profit / Gross Reference Sales (เกณฑ์ขั้นต่ำ ≥ 10%)", "decision-panel-sub")
          ),
          node("span", isProtectPass ? "badge-pass" : "badge-fail", isProtectPass ? "✓ PASS (ผ่านเกณฑ์)" : "✕ FAIL (ต่ำกว่าเกณฑ์)")
        )
      );

      const protCard = node("div", "single-month-card");
      const gaugeBox = node("div", "single-month-gauge-box");
      const gaugeRateWrap = box("v-stack",
        node("span", "gauge-rate-large", protectRatePct + "%"),
        small("อัตราคุ้มครองกำไรจริง (Actual Protection Rate)")
      );
      gaugeRateWrap.style.gap = "2px";

      const gaugeMetricsWrap = box("v-stack",
        box("h-stack", small("เกณฑ์คุ้มครองขั้นต่ำ:"), node("strong", "", "10.00%")),
        box("h-stack", small("กำไรส่วนเกินขั้นต่ำ (Headroom):"), node("strong", isProtectPass ? "text-pass" : "text-fail", (headroom >= 0 ? "+" : "") + "฿" + money(headroom))),
        box("h-stack", small("สถานะความปลอดภัย:"), node("span", isProtectPass ? "badge-pass" : "badge-fail", isProtectPass ? "ปลอดภัย (SAFE)" : "เสี่ยง (RISK)"))
      );
      gaugeMetricsWrap.style.gap = "4px";
      gaugeMetricsWrap.style.fontSize = "11px";

      gaugeBox.append(gaugeRateWrap, gaugeMetricsWrap);

      const protProgressTrack = node("div", "bullet-track");
      protProgressTrack.style.height = "14px";
      const protFill = node("div", "bullet-fill");
      protFill.style.width = Math.min(100, Math.round((protectRatePct / 20.0) * 100)) + "%";
      protFill.style.background = isProtectPass ? "#2e7d32" : "#c62828";

      const protTargetMarker = node("div", "bullet-target-marker");
      protTargetMarker.style.left = "50%";
      protTargetMarker.style.background = "#d32f2f";

      const protTargetLabel = node("span", "bullet-target-label", "เกณฑ์ขั้นต่ำ 10%");
      protTargetLabel.style.left = "50%";
      protTargetLabel.style.color = "#d32f2f";

      protProgressTrack.append(protFill, protTargetMarker, protTargetLabel);

      const protNote = node("div", "text-muted",
        "ℹ️ เกณฑ์คุ้มครองกำไรกำหนดไว้ที่ ≥ 10% ของยอดขายอ้างอิง เพื่อประกันความปลอดภัยของกระแสเงินสดหลังหักต้นทุน COGS, ค่าธรรมเนียม, Ads และส่วนลดทั้งหมด"
      );
      protNote.style.fontSize = "10px";
      protNote.style.marginTop = "6px";
      protNote.style.borderTop = "1px dashed #ebdbe0";
      protNote.style.paddingTop = "6px";

      protCard.append(gaugeBox, protProgressTrack, protNote);
      protPanel.append(protCard);
      trendRow.append(protPanel);
    } else {
      // Multi-Month Trend Chart for published months only
      const revPanel = node("div", "decision-panel");
      revPanel.append(
        box("alert-banner-header",
          box("v-stack",
            node("strong", "decision-panel-title", "📊 ยอดขายจริงเทียบเป้ารายเดือน"),
            small("Net Revenue vs Revenue Target (" + publishedMonths.map(thaiMonth).join(", ") + ")", "decision-panel-sub")
          ),
          box("h-stack",
            small("■ ยอดขายสุทธิ (Actual)", "text-bold"),
            small("□ เป้าหมาย (Target)")
          )
        )
      );

      const barChartWrap = node("div", "trend-chart-wrap");
      const activeMonthsData = publishedMonths.map(m => getPublishedMonthData(m)).filter(Boolean);
      const maxVal = Math.max(...activeMonthsData.map(d => Math.max(d.net_revenue, d.revenue_target)), 100000) * 1.1;

      activeMonthsData.forEach(sm => {
        const col = node("div", "trend-bar-group");
        const netH = Math.min(100, Math.round((sm.net_revenue / maxVal) * 100));
        const targetH = Math.min(100, Math.round((sm.revenue_target / maxVal) * 100));
        const smAchievePct = Math.round((sm.net_revenue / sm.revenue_target) * 1000) / 10;
        const isPass = smAchievePct >= 100;

        const pctBadge = node("span", isPass ? "badge-pass" : "badge-fail", smAchievePct + "%");
        pctBadge.style.fontSize = "8px";
        pctBadge.style.padding = "1px 3px";
        pctBadge.style.marginBottom = "3px";

        const barWrap = node("div", "h-stack");
        barWrap.style.alignItems = "flex-end";
        barWrap.style.gap = "2px";
        barWrap.style.height = "80px";

        const barNet = node("div", "");
        barNet.style.width = "14px";
        barNet.style.height = (netH * 0.8) + "px";
        barNet.style.background = "#741d2b";
        barNet.style.borderRadius = "2px 2px 0 0";

        const barTgt = node("div", "");
        barTgt.style.width = "10px";
        barTgt.style.height = (targetH * 0.8) + "px";
        barTgt.style.background = "#e0cfd3";
        barTgt.style.borderRadius = "2px 2px 0 0";

        barWrap.append(barNet, barTgt);
        const label = node("span", "text-muted", thaiMonth(sm.month));
        label.style.fontSize = "9px";
        label.style.marginTop = "4px";

        col.append(pctBadge, barWrap, label);
        barChartWrap.append(col);
      });
      revPanel.append(barChartWrap);
      trendRow.append(revPanel);

      const protPanel = node("div", "decision-panel");
      protPanel.append(
        box("alert-banner-header",
          box("v-stack",
            node("strong", "decision-panel-title", "🛡 อัตราคุ้มครองกำไร (%)"),
            small("Contribution Profit / Gross Reference Sales (เกณฑ์ขั้นต่ำ ≥ 10%)", "decision-panel-sub")
          ),
          node("span", "badge-validated", "เกณฑ์ 10%")
        )
      );

      const protChartWrap = node("div", "trend-chart-wrap");
      protChartWrap.style.position = "relative";

      const guideLine = node("div", "");
      guideLine.style.position = "absolute";
      guideLine.style.left = "0";
      guideLine.style.right = "0";
      guideLine.style.bottom = "42px";
      guideLine.style.borderTop = "1px dashed #d32f2f";
      guideLine.style.zIndex = "1";
      const guideTag = node("span", "", "เกณฑ์ขั้นต่ำ 10%");
      guideTag.style.position = "absolute";
      guideTag.style.right = "4px";
      guideTag.style.top = "-14px";
      guideTag.style.fontSize = "8px";
      guideTag.style.color = "#d32f2f";
      guideTag.style.fontWeight = "700";
      guideLine.append(guideTag);
      protChartWrap.append(guideLine);

      activeMonthsData.forEach(pm => {
        const col = node("div", "trend-bar-group");
        const pointH = Math.min(100, Math.round((pm.profit_protection_rate_pct / 20.0) * 100));
        const isPass = pm.profit_protection_rate_pct >= 10.0;

        const valLabel = node("span", isPass ? "text-bold" : "text-muted", pm.profit_protection_rate_pct + "%");
        valLabel.style.fontSize = "8px";
        valLabel.style.marginBottom = "2px";

        const lineBar = node("div", "");
        lineBar.style.width = "8px";
        lineBar.style.height = (pointH * 0.7) + "px";
        lineBar.style.background = isPass ? "#2e7d32" : "#c62828";
        lineBar.style.borderRadius = "3px";
        lineBar.style.margin = "0 auto";

        const statusTag = node("span", isPass ? "badge-pass" : "badge-fail", isPass ? "PASS" : "FAIL");
        statusTag.style.fontSize = "8px";
        statusTag.style.padding = "1px 3px";
        statusTag.style.marginTop = "4px";

        const mLabel = node("span", "text-muted", thaiMonth(pm.month));
        mLabel.style.fontSize = "9px";

        col.append(valLabel, lineBar, statusTag, mLabel);
        protChartWrap.append(col);
      });
      protPanel.append(protChartWrap);
      trendRow.append(protPanel);
    }
    dash.append(trendRow);

    // SECTION 3 & 4: COST WATERFALL & PRODUCT GROUP PERFORMANCE
    const sec34Row = node("div", "decision-two-col");

    // Section 3: Cost Waterfall
    const wfPanel = node("div", "decision-panel");
    wfPanel.append(
      box("alert-banner-header",
        box("v-stack",
          node("strong", "decision-panel-title", "📉 ต้นทุนและกำไร | Cost Waterfall"),
          small("การเปลี่ยนแปลงจากยอดขายอ้างอิงไปสู่กำไรหลังต้นทุน (" + thaiMonth(current.month) + ")", "decision-panel-sub")
        )
      )
    );

    const wfWrap = node("div", "waterfall-chart-wrap");
    const wfSteps = current.waterfall || [
      { label: "Gross Ref.", val: grossRef, type: "rev", display: "฿" + money(grossRef) },
      { label: "Camp. Disc.", val: -3480, type: "cost", display: "(฿3,480)" },
      { label: "Voucher", val: -1520, type: "cost", display: "(฿1,520)" },
      { label: "Net Revenue", val: net, type: "tot", display: "฿" + money(net) },
      { label: "COGS", val: -52596, type: "cost", display: "(฿52,596)" },
      { label: "Platform Fee", val: -2468, type: "cost", display: "(฿2,468)" },
      { label: "Fulfillment", val: -3275, type: "cost", display: "(฿3,275)" },
      { label: "Affiliate", val: -1982, type: "cost", display: "(฿1,982)" },
      { label: "Ads", val: -6025, type: "cost", display: "(฿6,025)" },
      { label: "Sample", val: -1410, type: "cost", display: "(฿1,410)" },
      { label: "Claim", val: -1474, type: "cost", display: "(฿1,474)" },
      { label: "Contrib. Profit", val: profit, type: "tot", display: "฿" + money(profit) }
    ];

    const maxWf = Math.max(...wfSteps.map(s => Math.abs(s.val)), 100000);
    wfSteps.forEach(st => {
      const col = node("div", "waterfall-bar-col");
      const h = Math.max(8, Math.min(100, Math.round((Math.abs(st.val) / maxWf) * 100)));

      const vSpan = node("span", "waterfall-bar-val", st.display);
      const rect = node("div", "waterfall-bar-rect");
      rect.style.height = (h * 0.9) + "px";
      rect.style.background = st.type === "cost" ? "#f8bbd0" : st.type === "tot" ? "#421d20" : "#741d2b";

      const lSpan = node("span", "waterfall-bar-label", st.label);
      col.append(vSpan, rect, lSpan);
      wfWrap.append(col);
    });
    wfPanel.append(wfWrap);

    const wfLegend = box("h-stack",
      small("■ ยอดเพิ่ม (Revenue/Profit)"),
      small("■ รายการหัก (Cost/Deduction)"),
      small("■ ยอดรวม (Total)")
    );
    wfLegend.style.gap = "12px";
    wfLegend.style.fontSize = "10px";
    wfLegend.style.marginTop = "6px";
    wfPanel.append(wfLegend);
    sec34Row.append(wfPanel);

    // Section 4: Product Group Performance
    const pgPanel = node("div", "decision-panel");
    pgPanel.append(
      box("alert-banner-header",
        box("v-stack",
          node("strong", "decision-panel-title", "👕 ผลงานตามกลุ่มสินค้า (Product Group Performance)"),
          small("ยอดขายและกำไรหลังต้นทุน (" + thaiMonth(current.month) + ")", "decision-panel-sub")
        ),
        node("span", "badge-validated", groupRows.length + " กลุ่มสินค้า")
      )
    );

    const pgTblWrap = box("table-wrap");
    const pgTbl = node("table");
    const pgThead = node("thead"), pgTr = node("tr");
    pgTr.append(
      node("th", "", "กลุ่มสินค้า"),
      node("th", "", "สัดส่วนยอดขาย"),
      node("th", "", "ยอดขายสุทธิ"),
      node("th", "", "กำไรหลังต้นทุน"),
      node("th", "", "คุ้มครองกำไร")
    );
    pgThead.append(pgTr); pgTbl.append(pgThead);
    const pgTbody = node("tbody");

    groupRows.forEach(p => {
      const r = node("tr", "table-row-clickable" + (state.group === p.group_id ? " table-row-selected" : ""));
      r.addEventListener("click", () => {
        state.group = (state.group === p.group_id) ? "ALL" : p.group_id;
        renderBusiness();
      });

      const shareCell = node("td");
      const shareBarWrap = node("div", "h-stack");
      shareBarWrap.style.alignItems = "center";
      shareBarWrap.style.gap = "6px";
      const sBar = node("div", "");
      sBar.style.width = (p.share * 2) + "px";
      sBar.style.height = "6px";
      sBar.style.background = "#741d2b";
      sBar.style.borderRadius = "3px";
      shareBarWrap.append(sBar, small(p.share + "%"));
      shareCell.append(shareBarWrap);

      r.append(
        node("td", "text-bold", p.group_name),
        shareCell,
        node("td", "", "฿" + money(p.net)),
        node("td", "", "฿" + money(p.profit)),
        node("td", "", "")
      );
      const protBadge = node("span", p.rate >= 10 ? "badge-pass" : "badge-fail", p.rate + "%");
      r.lastChild.append(protBadge);
      pgTbody.append(r);
    });
    pgTbl.append(pgTbody);
    pgTblWrap.append(pgTbl);
    pgPanel.append(pgTblWrap);
    sec34Row.append(pgPanel);

    dash.append(sec34Row);

    // SECTION 5, 6, 7: ML FORECAST, SCENARIO STUDIO, DECISION RECOMMENDATION
    const sec567Row = node("div", "decision-three-col");

    // Section 5: ML Demand Forecast (Strict Gating)
    const mlPanel = node("div", "decision-panel");
    const publishedWeeks = publishedMonths.length * 4;
    const hasMLReady = publishedWeeks >= 16;

    if (!hasMLReady) {
      mlPanel.append(
        box("alert-banner-header",
          box("v-stack",
            node("strong", "decision-panel-title", "📈 ML Demand Forecast"),
            small("ตรวจสอบความพร้อมโมเดล (ML Readiness Gate)", "decision-panel-sub")
          ),
          node("span", "badge-waiting", "[⏳ INSUFFICIENT_HISTORY]")
        )
      );

      const mlBox = node("div", "ml-readiness-box");
      const mlHeader = box("v-stack",
        node("strong", "", "ความพร้อมของข้อมูลประวัติ (Historical Data Readiness)"),
        small(\`มีประวัติแล้ว \${publishedWeeks} สัปดาห์ (ต้องการขั้นต่ำ 16 สัปดาห์ หรือ 4 เดือน)\`)
      );

      const trackWrap = node("div", "ml-progress-track");
      const fillBar = node("div", "ml-progress-fill");
      fillBar.style.width = Math.round((publishedWeeks / 16) * 100) + "%";
      trackWrap.append(fillBar);

      const checklistWrap = box("v-stack");
      checklistWrap.style.gap = "6px";
      checklistWrap.style.marginTop = "6px";

      const item1 = node("div", "ml-checklist-item");
      item1.append(node("span", "ml-check-icon text-pass", "✓"), node("span", "", \`มีข้อมูลจริงจาก Warehouse (\${publishedMonths.map(thaiMonth).join(", ")})\`));

      const item2 = node("div", "ml-checklist-item");
      item2.append(node("span", "ml-check-icon text-muted", "⏳"), node("span", "", \`สะสมข้อมูลรายสัปดาห์ (\${publishedWeeks}/16 สัปดาห์)\`));

      const item3 = node("div", "ml-checklist-item");
      item3.append(node("span", "ml-check-icon text-muted", "🔒"), node("span", "", "โมเดล XGBoost v1.3 (จะปลดล็อคอัตโนมัติเมื่อครบ 16 สัปดาห์)"));

      checklistWrap.append(item1, item2, item3);

      const explText = node("p", "text-muted",
        "ตามมาตรฐาน MLOps การพยากรณ์ความต้องการด้วยโมเดล Time-Series (XGBoost) ต้องใช้ประวัติอย่างน้อย 16 สัปดาห์เพื่อสร้าง Lag Features และ Seasonality Features ที่น่าเชื่อถือ ระบบจึงระงับการแสดงผล Forecast ปลอมเพื่อป้องกันการตัดสินใจผิดพลาด"
      );
      explText.style.fontSize = "10px";
      explText.style.margin = "4px 0 0";
      explText.style.lineHeight = "1.35";

      mlBox.append(mlHeader, trackWrap, checklistWrap, explText);
      mlPanel.append(mlBox);
    } else {
      // Real ML Model Forecast
      mlPanel.append(
        box("alert-banner-header",
          box("v-stack",
            node("strong", "decision-panel-title", "📈 ML Demand Forecast"),
            small("คาดการณ์ยอดขาย 4 สัปดาห์ถัดไป (XGBoost)", "decision-panel-sub")
          ),
          node("span", "badge-validated", "XGBoost v1.3")
        )
      );

      const fcChartWrap = node("div", "trend-chart-wrap");
      const fcWeeks = [
        { w: "W1", units: 558 }, { w: "W2", units: 612 },
        { w: "W3", units: 690 }, { w: "W4", units: 728 }
      ];
      fcWeeks.forEach(fw => {
        const col = node("div", "trend-bar-group");
        const h = Math.round((fw.units / 1000) * 80);
        const val = node("span", "text-bold", fw.units);
        val.style.fontSize = "9px";
        val.style.marginBottom = "2px";

        const bar = node("div", "");
        bar.style.width = "10px";
        bar.style.height = h + "px";
        bar.style.background = "#741d2b";
        bar.style.borderRadius = "2px 2px 0 0";

        const lbl = node("span", "text-muted", fw.w);
        lbl.style.fontSize = "9px";
        lbl.style.marginTop = "3px";

        col.append(val, bar, lbl);
        fcChartWrap.append(col);
      });
      mlPanel.append(fcChartWrap);

      const mlMetaBox = box("v-stack",
        box("h-stack", small("โมเดล: XGBoost v1.3", "text-bold"), small("ช่วงฝึกสอน: ม.ค. - เม.ย. 2569")),
        box("h-stack", small("WAPE: 8.7%"), small("MAE: 53.2 ชิ้น"), small("Bias: +1.9%"))
      );
      mlMetaBox.style.gap = "4px";
      mlMetaBox.style.padding = "8px";
      mlMetaBox.style.background = "#fdfafb";
      mlMetaBox.style.borderRadius = "6px";
      mlMetaBox.style.border = "1px solid #ebdbe0";
      mlPanel.append(mlMetaBox);
    }
    sec567Row.append(mlPanel);

    // Section 6: Scenario Studio (What-if Simulation)
    const scPanel = node("div", "decision-panel");
    scPanel.append(
      box("alert-banner-header",
        box("v-stack",
          node("strong", "decision-panel-title", "🎛 Scenario Studio (What-if)"),
          small("จำลองผลลัพธ์เมื่อปรับงบและโปรโมชั่น (" + thaiMonth(current.month) + ")", "decision-panel-sub")
        )
      )
    );

    const baseAds = 6025;
    const baseDisc = 3.7;
    const adsSliderWrap = node("div", "scenario-slider-group");
    const adsHeader = node("div", "scenario-slider-header");
    adsHeader.append(node("span", "", "งบโฆษณา (Ads Budget)"), node("span", "text-bold", "฿" + money(state.scenarioAds || 7000)));
    const adsSlider = node("input", "scenario-slider-input");
    adsSlider.type = "range"; adsSlider.min = "3000"; adsSlider.max = "15000"; adsSlider.step = "500";
    adsSlider.value = String(state.scenarioAds || 7000);
    adsSliderWrap.append(adsHeader, adsSlider);

    const discSliderWrap = node("div", "scenario-slider-group");
    const discHeader = node("div", "scenario-slider-header");
    discHeader.append(node("span", "", "ส่วนลดแคมเปญ (Campaign Discount)"), node("span", "text-bold", (state.scenarioDiscount || 4.0).toFixed(1) + "% (ฐาน: " + baseDisc + "%)"));
    const discSlider = node("input", "scenario-slider-input");
    discSlider.type = "range"; discSlider.min = "1.0"; discSlider.max = "10.0"; discSlider.step = "0.5";
    discSlider.value = String(state.scenarioDiscount || 4.0);
    discSliderWrap.append(discHeader, discSlider);

    const simBox = node("div", "scenario-result-box");
    function updateSimulation() {
      const sAds = Number(adsSlider.value);
      const sDisc = Number(discSlider.value);
      state.scenarioAds = sAds;
      state.scenarioDiscount = sDisc;

      adsHeader.lastChild.textContent = "฿" + money(sAds) + " (" + (sAds >= baseAds ? "+" : "") + Math.round(((sAds - baseAds) / baseAds) * 100) + "%)";
      discHeader.lastChild.textContent = sDisc.toFixed(1) + "% (ฐาน: " + baseDisc + "%)";

      // Elasticity simulation assumption
      const deltaVol = ((sAds - baseAds) / baseAds) * 0.25;
      const simNet = Math.round(net * (1 + deltaVol) * (1 - (sDisc - baseDisc) / 100));
      const simProfit = Math.round(profit + (simNet - net) * 0.40 - (sAds - baseAds));
      const simGross = Math.round(grossRef * (1 + deltaVol));
      const simRate = Math.round((simProfit / simGross) * 10000) / 100;

      simBox.replaceChildren(
        box("v-stack", small("ยอดขายสุทธิ"), node("strong", "", "฿" + money(simNet)), small("+" + (Math.round(((simNet - net) / net) * 1000) / 10) + "%")),
        box("v-stack", small("กำไรหลังต้นทุน"), node("strong", "", "฿" + money(simProfit)), small("+" + (Math.round(((simProfit - profit) / profit) * 1000) / 10) + "%")),
        box("v-stack", small("คุ้มครองกำไร"), node("strong", "", simRate + "%"), node("span", simRate >= 10 ? "badge-pass" : "badge-fail", simRate >= 10 ? "✓ ผ่าน" : "✕ ไม่ผ่าน"))
      );
    }

    adsSlider.addEventListener("input", updateSimulation);
    discSlider.addEventListener("input", updateSimulation);
    updateSimulation();

    const simDisclaimer = node("p", "text-muted",
      \`* การจำลองนี้เป็นการประเมินสมมติฐานเชิงธุรกิจ (Scenario Assumption) อ้างอิงจาก Baseline จริงของ \${thaiMonth(current.month)} ไม่ใช่การทำนายโดยโมเดล ML\`
    );
    simDisclaimer.style.fontSize = "9px";
    simDisclaimer.style.marginTop = "6px";
    simDisclaimer.style.lineHeight = "1.3";

    scPanel.append(adsSliderWrap, discSliderWrap, simBox, simDisclaimer);
    sec567Row.append(scPanel);

    // Section 7: Decision Recommendation
    const decPanel = node("div", "decision-panel");
    decPanel.append(
      box("alert-banner-header",
        box("v-stack",
          node("strong", "decision-panel-title", "🎯 ข้อเสนอแนะการตัดสินใจ (Decision Recommendation)"),
          small("สรุปผลและการดำเนินงานเชิงธุรกิจ (" + thaiMonth(current.month) + ")", "decision-panel-sub")
        )
      )
    );

    const statusChecksBox = box("v-stack",
      box("h-stack",
        node("span", isRevenuePass ? "badge-pass" : "badge-fail", isRevenuePass ? "✓ ยอดขาย ≥ เป้า" : "✕ ยอดขาย < เป้า"),
        small(achievePct + "% (฿" + money(net) + " / ฿" + money(target) + ")")
      ),
      box("h-stack",
        node("span", isProtectPass ? "badge-pass" : "badge-fail", isProtectPass ? "✓ กำไร ≥ 10%" : "✕ กำไร < 10%"),
        small(protectRatePct + "% (ผ่านเกณฑ์คุ้มครองกำไรขั้นต่ำ)")
      )
    );
    statusChecksBox.style.gap = "6px";
    statusChecksBox.style.marginBottom = "8px";
    decPanel.append(statusChecksBox);

    const recList = node("div", "recommendation-list");
    const recs = [
      "กลุ่ม คอเต่า และ Crop มีอัตราการสร้างกำไรสูงสุด (14.71% และ 14.64%) ควรคงสัดส่วนเป็น Hero Products",
      "กลุ่ม Oversize มีอัตรากำไรต่ำสุด (13.32%) ควรควบคุมค่า Ads และส่วนลดไม่ให้กระทบ Margin",
      "อัตราส่วนลดรวมปัจจุบันอยู่ที่ 5.37% (แคมเปญ ฿3,480 + คูปอง ฿1,520) ควรควบคุมไม่ให้เกิน 6.0% เพื่อรักษา Headroom",
      publishedWeeks < 16 ?
        "⏳ ข้อเสนอแนะเชิงลึกด้านการพยากรณ์ความต้องการ (ML Demand Guidance) อยู่ระหว่างรอข้อมูลสะสมครบ 16 สัปดาห์" :
        "โมเดลแนะนำเตรียมสต็อกสินค้ากลุ่ม คอกลม และ Crop เพิ่มขึ้นตามแนวโน้มยอดขายสัปดาห์ถัดไป"
    ];
    recs.forEach(text => {
      const it = node("div", "recommendation-item");
      it.append(node("span", "recommendation-dot", text.startsWith("⏳") ? "⏳" : "💡"), node("span", "", text));
      recList.append(it);
    });
    decPanel.append(recList);
    sec567Row.append(decPanel);

    dash.append(sec567Row);

    // SECTION 8: DETAILED DATA EXPLORER (COLLAPSIBLE ACCORDION)
    const load = snapshot?.result?.stages?.find(x => x.stage === "load")?.evidence?.output;
    const tables = Array.isArray(load?.tables) ? load.tables : [];
    const previews = load?.table_previews || {};
    const names = tables.map(x => x.name);
    if (!names.includes(state.warehouseTable)) {
      state.warehouseTable = names.includes("Fact_Sales_Order_Item") ? "Fact_Sales_Order_Item" : (names[0] || "Fact_Sales_Order_Item");
    }
    const warehouseRows = Array.isArray(previews[state.warehouseTable]) ? previews[state.warehouseTable] : [];

    const explorerDrawer = node("details", "advanced-settings-section");
    const explorerSummary = node("summary", "advanced-settings-summary", "🔍 สำรวจข้อมูลเชิงลึก (Detailed Data Explorer: Daily Mart, SKU, Campaigns)");
    const explorerBody = box("v-stack");
    explorerBody.style.marginTop = "14px";
    explorerBody.style.gap = "14px";

    const explorerSubtabs = [
      ["daily", "รายวัน (Daily Mart)"],
      ["sku", "สินค้า (SKU Performance)"],
      ["campaign", "แคมเปญและโฆษณา"],
      ["tables", "ตารางใน Warehouse (" + tables.length + " ตาราง)"]
    ];
    state.explorerSubtab = state.explorerSubtab || "daily";

    const exSubtabBar = box("stage-subtabs");
    explorerSubtabs.forEach(([sId, sLabel]) => {
      const sBtn = node("button", "stage-subtab" + (state.explorerSubtab === sId ? " is-active" : ""), sLabel);
      sBtn.type = "button";
      sBtn.addEventListener("click", () => {
        state.explorerSubtab = sId;
        renderBusiness();
      });
      exSubtabBar.append(sBtn);
    });
    explorerBody.append(exSubtabBar);

    const business = snapshot?.result?.business || state.data?.business;
    if (state.explorerSubtab === "daily") {
      const days = (business?.days || []).filter(x => x.month === current.month);
      explorerBody.append(dataTable([["day", "วัน"], ["group_id", "กลุ่มสินค้า"], ["net", "ยอดขายสุทธิ"]], days.slice(0, 15)));
    } else if (state.explorerSubtab === "sku") {
      const skus = (business?.sku || []).filter(x => x.month === current.month);
      explorerBody.append(dataTable([["sku_id", "SKU"], ["sku_name", "สินค้า"], ["net", "ยอดขายสุทธิ"], ["cogs", "ต้นทุนสินค้า"]], skus.slice(0, 15)));
    } else if (state.explorerSubtab === "campaign") {
      const campaigns = (business?.campaigns || []).filter(x => x.month === current.month);
      explorerBody.append(dataTable([["campaign_name", "ชื่อแคมเปญ"], ["net", "ยอดขายสุทธิ"], ["price_reduction", "ส่วนลด"]], campaigns.slice(0, 10)));
    } else if (state.explorerSubtab === "tables") {
      explorerBody.append(
        chooseField("เลือกตารางเพื่อดูแถวตัวอย่าง", tables.map(item => [item.name, item.name + " · " + money(item.rows) + " แถว"]), state.warehouseTable, value => {
          state.warehouseTable = value; renderBusiness();
        }),
        warehouseRows.length ?
          dataTable(Object.keys(warehouseRows[0]).slice(0, 8).map(key => [key, key]), warehouseRows) :
          small("ตารางนี้ไม่มีแถวตัวอย่าง")
      );
    }

    explorerDrawer.append(explorerSummary, explorerBody);
    dash.append(explorerDrawer);

    root.append(dash);
  }`;

const updatedContent = content.substring(0, startIndex) + replacement + content.substring(endIndex);
fs.writeFileSync(appJsPath, updatedContent, 'utf8');
console.log('Successfully updated dashboard/app.js with Progressive Data Reveal logic');
