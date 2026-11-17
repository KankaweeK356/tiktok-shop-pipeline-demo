const fs = require('fs');

const path = 'dashboard/app.js';
let code = fs.readFileSync(path, 'utf8');

// Normalize CRLF to LF for reliable matching
let norm = code.replace(/\r\n/g, '\n');

// 1. Update Stages rendering (Lines ~3414 to ~3475)
const oldStagesBlock = `    // 4. Five Numbered Expandable Stages
    const currentViewBatch = state.viewedBatch || state.notebookBatch || "initial";
    const entries = state.savedLabManifest?.runs?.filter(x => x.batch === currentViewBatch) || [];

    NOTEBOOK_STAGES.forEach(([id, title, description], index) => {
      const entry = entries.find(x => x.stage === id), active = state.notebookStage === id;
      const cell = node("section", "notebook-cell" + (active ? " is-open" : ""));
      const head = node("button", "notebook-cell-head"); head.type = "button";
      head.setAttribute("aria-expanded", String(active));
      const savedResult = state.batchResults[currentViewBatch]?.[id];
      const liveStep = state.batchRun.batch === currentViewBatch ?
        state.batchRun.stages.find(x => x.index === index) : null;
      const runningNow = liveStep?.status === "in_progress" || (state.stageBusy && (state.nextSourceBatch || "initial") === currentViewBatch && state.notebookStage === id);
      const isFailed = (currentViewBatch === "incremental_02" && id === "transform" && state.marchBlocked);

      head.append(node("span", "notebook-number", String(index + 1)),
        box("notebook-cell-title", node("strong", "", title), small(description)),
        node("span", "notebook-cell-state",
          isFailed ? "ผิดพลาด / บล็อก" :
          (savedResult || liveStep?.conclusion === "success" ? "ผ่านแล้ว" :
           runningNow ? "กำลังรัน" : "รอรัน")
        ));
      head.addEventListener("click", () => {
        state.notebookStage = id; state.savedLabReceipt = null; renderPipeline();
      }); cell.append(head);
      if (active) {
        const body = box("notebook-cell-body");

        // Subtabs: Preview | Input | Process | Validation (ตรวจสอบข้อมูล) | Output
        const activeSubtab = state.stageActiveSubtab[id] || "preview";
        const subtabsBar = box("stage-subtabs");
        [["preview", "Preview"], ["input", "Input"], ["process", "Process"], ["validation", "ตรวจสอบข้อมูล"], ["output", "Output"]].forEach(([subId, subLabel]) => {
          const subBtn = node("button", "stage-subtab" + (activeSubtab === subId ? " is-active" : ""), subLabel);
          subBtn.type = "button";
          subBtn.addEventListener("click", () => {
            state.stageActiveSubtab[id] = subId;
            renderPipeline();
          });
          subtabsBar.append(subBtn);
        });
        body.append(subtabsBar);

        const evidence = savedResult?.evidence;

        if (activeSubtab === "preview") {
          const isInitial = currentViewBatch === "initial";
          const hasSaved = Boolean(savedResult);
          if (!isInitial && !hasSaved) {
            const emptyBox = box("empty-state-card",
              node("div", "empty-state-icon", "⏳"),
              node("strong", "", \`รอบข้อมูล: \${thaiMonth(sourceMonthForBatch(currentViewBatch))} (ยังไม่ได้เริ่มรัน)\`),
              small(\`ขั้นตอนที่ \${index + 1}: \${title} — อยู่ในสถานะรอการประมวลผล (Waiting for Execution)\`),
              box("h-stack",
                node("span", "badge-waiting", "สถานะ: รอรัน"),
                node("span", "badge-neutral", \`ชุดข้อมูล: classroom-source-\${sourceMonthForBatch(currentViewBatch)}.zip\`)
              )
            );
            body.append(emptyBox);
          } else {`;

const newStagesBlock = `    // 4. Five Numbered Expandable Stages
    const currentViewBatch = state.viewedBatch || state.notebookBatch || "initial";
    const batchRun = (state.currentCycleRuns || []).find(x => (x.source_batch === currentViewBatch || x.batch === currentViewBatch) && x.status === "SUCCEEDED");
    const isBatchSucceeded = Boolean(batchRun) || Boolean(state.batchSummaries[currentViewBatch]);
    const isEvidenceUnavailable = Boolean(state.batchResults[currentViewBatch]?._evidenceUnavailable);
    const activeExecutionBatch = state.nextSourceBatch || "initial";
    const entries = state.savedLabManifest?.runs?.filter(x => x.batch === currentViewBatch) || [];

    // Header indicating Viewed Batch vs Active Execution Batch (Decoupled State)
    const viewHeaderBox = box("h-stack");
    viewHeaderBox.style.justifyContent = "space-between";
    viewHeaderBox.style.alignItems = "center";
    viewHeaderBox.style.padding = "10px 16px";
    viewHeaderBox.style.background = "var(--color-surface, #FFFFFF)";
    viewHeaderBox.style.borderRadius = "8px";
    viewHeaderBox.style.border = "1px solid var(--color-border, #E2D9D2)";
    viewHeaderBox.style.marginBottom = "14px";

    const viewTitle = box("h-stack",
      node("span", "text-bold", \`👀 แสดงผลลัพธ์รอบข้อมูล: \${thaiMonth(sourceMonthForBatch(currentViewBatch))}\`),
      node("span", isBatchSucceeded ? "badge-pass" : "badge-neutral", isBatchSucceeded ? "✓ รันสำเร็จแล้ว" : "⏳ รอบที่เลือกยังไม่รัน")
    );
    viewTitle.style.gap = "8px";
    viewTitle.style.alignItems = "center";

    const execPointer = box("h-stack",
      small(\`สถานะคิวรันจริง (Execution Pointer): \${thaiMonth(sourceMonthForBatch(activeExecutionBatch))}\`),
      node("span", "badge-neutral", activeExecutionBatch === "initial" ? "Initial" : activeExecutionBatch)
    );
    execPointer.style.gap = "8px";
    execPointer.style.alignItems = "center";

    viewHeaderBox.append(viewTitle, execPointer);
    root.append(viewHeaderBox);

    NOTEBOOK_STAGES.forEach(([id, title, description], index) => {
      const entry = entries.find(x => x.stage === id), active = state.notebookStage === id;
      const cell = node("section", "notebook-cell" + (active ? " is-open" : ""));
      const head = node("button", "notebook-cell-head"); head.type = "button";
      head.setAttribute("aria-expanded", String(active));
      const savedResult = state.batchResults[currentViewBatch]?.[id];
      const liveStep = state.batchRun.batch === currentViewBatch ?
        state.batchRun.stages.find(x => x.index === index) : null;
      const runningNow = liveStep?.status === "in_progress" || (state.stageBusy && (state.nextSourceBatch || "initial") === currentViewBatch && state.notebookStage === id);
      const isFailed = (currentViewBatch === "incremental_02" && id === "transform" && state.marchBlocked);

      head.append(node("span", "notebook-number", String(index + 1)),
        box("notebook-cell-title", node("strong", "", title), small(description)),
        node("span", "notebook-cell-state",
          isFailed ? "ผิดพลาด / บล็อก" :
          (savedResult || isBatchSucceeded || liveStep?.conclusion === "success" ? "ผ่านแล้ว" :
           runningNow ? "กำลังรัน" : "รอรัน")
        ));
      head.addEventListener("click", () => {
        state.notebookStage = id; state.savedLabReceipt = null; renderPipeline();
      }); cell.append(head);
      if (active) {
        const body = box("notebook-cell-body");

        // Subtabs: Preview | Input | Process | Validation (ตรวจสอบข้อมูล) | Output
        const activeSubtab = state.stageActiveSubtab[id] || "preview";
        const subtabsBar = box("stage-subtabs");
        [["preview", "Preview"], ["input", "Input"], ["process", "Process"], ["validation", "ตรวจสอบข้อมูล"], ["output", "Output"]].forEach(([subId, subLabel]) => {
          const subBtn = node("button", "stage-subtab" + (activeSubtab === subId ? " is-active" : ""), subLabel);
          subBtn.type = "button";
          subBtn.addEventListener("click", () => {
            state.stageActiveSubtab[id] = subId;
            renderPipeline();
          });
          subtabsBar.append(subBtn);
        });
        body.append(subtabsBar);

        const evidence = savedResult?.evidence;

        if (activeSubtab === "preview") {
          const isInitial = currentViewBatch === "initial";
          const hasSaved = Boolean(savedResult);
          if (isEvidenceUnavailable) {
            const runId = state.batchResults[currentViewBatch]?._runId || batchRun?.run_id || state.batchRunIds[currentViewBatch] || "N/A";
            const unavailableBox = box("empty-state-card",
              node("div", "empty-state-icon", "📁"),
              node("strong", "", \`รอบข้อมูล: \${thaiMonth(sourceMonthForBatch(currentViewBatch))} (ประมวลผลสำเร็จแล้ว)\`),
              small(\`ขั้นตอนที่ \${index + 1}: \${title} — สถานะหลักฐาน: EVIDENCE_UNAVAILABLE (ไม่พบไฟล์บันทึกผลลัพธ์ใน Storage สำหรับ Run ID: \${runId})\`),
              box("h-stack",
                node("span", "badge-pass", "สถานะการรัน: สำเร็จ (SUCCEEDED)"),
                node("span", "badge-waiting", "EVIDENCE_UNAVAILABLE"),
                node("span", "badge-neutral", \`ชุดข้อมูล: classroom-source-\${sourceMonthForBatch(currentViewBatch)}.zip\`)
              )
            );
            body.append(unavailableBox);
          } else if (!isInitial && !hasSaved && !isBatchSucceeded) {
            const emptyBox = box("empty-state-card",
              node("div", "empty-state-icon", "⏳"),
              node("strong", "", \`รอบข้อมูล: \${thaiMonth(sourceMonthForBatch(currentViewBatch))} (ยังไม่ได้เริ่มรัน)\`),
              small(\`ขั้นตอนที่ \${index + 1}: \${title} — อยู่ในสถานะรอการประมวลผล (Waiting for Execution)\`),
              box("h-stack",
                node("span", "badge-waiting", "สถานะ: รอรัน"),
                node("span", "badge-neutral", \`ชุดข้อมูล: classroom-source-\${sourceMonthForBatch(currentViewBatch)}.zip\`)
              )
            );
            body.append(emptyBox);
          } else {`;

if (norm.includes(oldStagesBlock)) {
  norm = norm.replace(oldStagesBlock, newStagesBlock);
  console.log('1. Replaced Stages Block with decoupled execution & evidence unavailable check');
} else {
  console.log('1. oldStagesBlock not found!');
}

// 2. Update Scenario Studio & Decision Recommendation (Lines ~990 to ~1082)
const oldSecBlock = `    const adsSliderWrap = node("div", "scenario-slider-group");
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
    decPanel.append(recList);`;

const newSecBlock = `    const adsSliderWrap = node("div", "scenario-slider-group");
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

    const liftSliderWrap = node("div", "scenario-slider-group");
    const liftHeader = node("div", "scenario-slider-header");
    const defaultLift = 4.1;
    const currentLift = state.scenarioLift !== undefined ? state.scenarioLift : defaultLift;
    liftHeader.append(node("span", "", "สมมติฐานยอดขายที่เพิ่มขึ้น (Assumed Demand Lift)"), node("span", "text-bold", (currentLift >= 0 ? "+" : "") + currentLift.toFixed(1) + "%"));
    const liftSlider = node("input", "scenario-slider-input");
    liftSlider.type = "range"; liftSlider.min = "-10.0"; liftSlider.max = "25.0"; liftSlider.step = "0.5";
    liftSlider.value = String(currentLift);
    liftSliderWrap.append(liftHeader, liftSlider);

    const simBox = node("div", "scenario-result-box");
    function updateSimulation() {
      const sAds = Number(adsSlider.value);
      const sDisc = Number(discSlider.value);
      const sLift = Number(liftSlider.value);
      state.scenarioAds = sAds;
      state.scenarioDiscount = sDisc;
      state.scenarioLift = sLift;

      adsHeader.lastChild.textContent = "฿" + money(sAds) + " (" + (sAds >= baseAds ? "+" : "") + Math.round(((sAds - baseAds) / baseAds) * 100) + "%)";
      discHeader.lastChild.textContent = sDisc.toFixed(1) + "% (ฐาน: " + baseDisc + "%)";
      liftHeader.lastChild.textContent = (sLift >= 0 ? "+" : "") + sLift.toFixed(1) + "%";

      // Transparent simulation formula based on user-controlled demand lift
      const simNet = Math.round(net * (1 + sLift / 100) * (1 - (sDisc - baseDisc) / 100));
      const simProfit = Math.round(profit + (simNet - net) * 0.40 - (sAds - baseAds));
      const simGross = Math.round(grossRef * (1 + sLift / 100));
      const simRate = Math.round((simProfit / simGross) * 10000) / 100;

      simBox.replaceChildren(
        box("v-stack", small("ยอดขายสุทธิ"), node("strong", "", "฿" + money(simNet)), small((simNet >= net ? "+" : "") + (Math.round(((simNet - net) / net) * 1000) / 10) + "%")),
        box("v-stack", small("กำไรหลังต้นทุน"), node("strong", "", "฿" + money(simProfit)), small((simProfit >= profit ? "+" : "") + (Math.round(((simProfit - profit) / profit) * 1000) / 10) + "%")),
        box("v-stack", small("คุ้มครองกำไร"), node("strong", "", simRate + "%"), node("span", simRate >= 10 ? "badge-pass" : "badge-fail", simRate >= 10 ? "✓ ผ่าน" : "✕ ไม่ผ่าน"))
      );
    }

    adsSlider.addEventListener("input", updateSimulation);
    discSlider.addEventListener("input", updateSimulation);
    liftSlider.addEventListener("input", updateSimulation);
    updateSimulation();

    const simDisclaimer = node("p", "text-muted",
      \`* การจำลองนี้เป็นการประเมินสมมติฐานเชิงธุรกิจ (Scenario Assumption) อ้างอิงจาก Baseline จริงของ \${thaiMonth(current.month)} ไม่ใช่การทำนายโดยโมเดล ML\`
    );
    simDisclaimer.style.fontSize = "9px";
    simDisclaimer.style.marginTop = "6px";
    simDisclaimer.style.lineHeight = "1.3";

    scPanel.append(adsSliderWrap, discSliderWrap, liftSliderWrap, simBox, simDisclaimer);
    sec567Row.append(scPanel);

    // Section 7: Decision Recommendation (Rule-Based Decision Support Engine)
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
    const recs = [];

    // [R01-REV-GAP / R01-REV-ACHIEVE]
    if (isRevenuePass) {
      recs.push({
        id: "R01-REV-ACHIEVE",
        icon: "🎯",
        tag: "[R01-REV-ACHIEVE]",
        text: \`ยอดขายสุทธิ ฿\${money(net)} บรรลุเป้าหมาย (\${achievePct}% ของเป้า ฿\${money(target)}) ส่วนต่างเกินเป้า +฿\${money(net - target)}\`
      });
    } else {
      recs.push({
        id: "R01-REV-GAP",
        icon: "⚠️",
        tag: "[R01-REV-GAP]",
        text: \`ยอดขายสุทธิ ฿\${money(net)} ต่ำกว่าเป้าหมาย (\${achievePct}% ของเป้า ฿\${money(target)}) ขาดอีก ฿\${money(target - net)}\`
      });
    }

    // [R02-PROT-HEADROOM / R02-PROT-SHORTFALL]
    if (isProtectPass) {
      recs.push({
        id: "R02-PROT-HEADROOM",
        icon: "🛡️",
        tag: "[R02-PROT-HEADROOM]",
        text: \`อัตราคุ้มครองกำไร \${protectRatePct}% ผ่านเกณฑ์ขั้นต่ำ (≥10%) มี Profit Headroom ส่วนเกิน ฿\${money(headroom)}\`
      });
    } else {
      recs.push({
        id: "R02-PROT-SHORTFALL",
        icon: "🚨",
        tag: "[R02-PROT-SHORTFALL]",
        text: \`อัตราคุ้มครองกำไร \${protectRatePct}% ต่ำกว่าเกณฑ์ขั้นต่ำ 10% ขาดทุนหรือตกเกณฑ์ไป ฿\${money(Math.abs(headroom))}\`
      });
    }

    // [R03-HERO-PORTFOLIO] & [R04-MARGIN-WATCH]
    if (groups.length > 0) {
      const sortedGroups = groups.slice().sort((a, b) => (b.margin_pct ?? 0) - (a.margin_pct ?? 0));
      const heroGroup = sortedGroups[0];
      const watchGroup = sortedGroups[sortedGroups.length - 1];
      recs.push({
        id: "R03-HERO-PORTFOLIO",
        icon: "⭐",
        tag: "[R03-HERO-PORTFOLIO]",
        text: \`กลุ่ม \${heroGroup.group_name} มีอัตรากำไรสูงสุด (\${heroGroup.margin_pct ?? 14.71}%) ควรคงสัดส่วนเป็น Hero Products และจัดสรรงบ Ads หลัก\`
      });
      recs.push({
        id: "R04-MARGIN-WATCH",
        icon: "🔍",
        tag: "[R04-MARGIN-WATCH]",
        text: \`กลุ่ม \${watchGroup.group_name} มีอัตรากำไรต่ำสุด (\${watchGroup.margin_pct ?? 13.32}%) ควรควบคุมค่า Ads และส่วนลดไม่ให้กระทบ Margin รวม\`
      });
    }

    // [R05-DISC-CEILING]
    const discPct = grossRef > 0 ? ((baseDiscNet / grossRef) * 100).toFixed(2) : "5.37";
    recs.push({
      id: "R05-DISC-CEILING",
      icon: "🏷️",
      tag: "[R05-DISC-CEILING]",
      text: \`อัตราส่วนลดรวมปัจจุบัน \${discPct}% ควบคุมส่วนลดรวม (Campaign + Voucher) ไม่เกิน 6.0% เพื่อรักษา Headroom คุ้มครองกำไร\`
    });

    // [R06-ML-INSUFFICIENT / R06-ML-READY]
    if (publishedWeeks < 16) {
      recs.push({
        id: "R06-ML-INSUFFICIENT",
        icon: "⏳",
        tag: "[R06-ML-INSUFFICIENT]",
        text: \`ระบบ ML Demand Forecasting ต้องการประวัติข้อมูลสะสมอย่างน้อย 16 สัปดาห์ (ปัจจุบัน \${publishedWeeks}/16 สัปดาห์) การตัดสินใจช่วงนี้ให้ใช้นโยบาย Rule-based แนะนำข้างต้น\`
      });
    } else {
      recs.push({
        id: "R06-ML-READY",
        icon: "🤖",
        tag: "[R06-ML-READY]",
        text: \`โมเดล ML มีประวัติข้อมูลครบถ้วน พร้อมวิเคราะห์และแนะนำการสต็อกสินค้าตามแนวโน้ม 4 สัปดาห์ถัดไป\`
      });
    }

    recs.forEach(r => {
      const it = node("div", "recommendation-item");
      const tagBadge = node("span", "badge-neutral", r.tag);
      tagBadge.style.fontSize = "10px";
      tagBadge.style.marginRight = "6px";
      tagBadge.style.fontWeight = "600";
      tagBadge.style.letterSpacing = "0.3px";
      it.append(
        node("span", "recommendation-dot", r.icon),
        box("v-stack",
          tagBadge,
          node("span", "", r.text)
        )
      );
      recList.append(it);
    });
    decPanel.append(recList);`;

if (norm.includes(oldSecBlock)) {
  norm = norm.replace(oldSecBlock, newSecBlock);
  console.log('2. Replaced Scenario Studio & Decision Recommendation Block with Rule IDs');
} else {
  console.log('2. oldSecBlock not found!');
}

fs.writeFileSync(path, norm, 'utf8');
console.log('Done update_app_stage_and_decision.cjs');
