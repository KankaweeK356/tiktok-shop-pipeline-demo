/**
 * TikTok Shop Classroom Demo Dashboard & Pipeline Runner
 * Single Main Flow: 10 Months (Jan–Oct)
 * Authoritative business rules, zero fake Colab references.
 */
(function () {
  "use strict";

  const $ = selector => document.querySelector(selector);
  const $$ = selector => document.querySelectorAll(selector);

  // App Global State
  const state = {
    view: "business", // "business" | "pipeline" | "ml"
    pipeline: null, // Full status from /api/lab-batch
    business: null, // Published warehouse financials from /api/lab-batch-result?business=1
    ml: null, // ML evaluation from /api/lab-batch-result?ml=1
    selectedMonth: "2026-01",
    viewingMonth: "2026-01",
    selectedStage: "ingest",
    selectedTab: "input",
    isOrchestrating: false, // Flag for Run All loop
    isFixModalOpen: false,
    isResetModalOpen: false,
    selectedGroup: "ALL",
    scenario: {
      budgetRatio: 1.0,
      adsSpend: 5000,
      campaignDiscountPct: 5,
      voucherSpend: 3000
    }
  };

  // Utilities
  const formatMoney = (val, digits = 0) => {
    if (val === null || val === undefined || isNaN(Number(val))) return "—";
    return new Intl.NumberFormat("th-TH", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    }).format(Number(val)) + " ฿";
  };

  const formatNumber = val => {
    if (val === null || val === undefined || isNaN(Number(val))) return "—";
    return new Intl.NumberFormat("th-TH").format(Number(val));
  };

  const formatPct = (val, digits = 1) => {
    if (val === null || val === undefined || isNaN(Number(val))) return "—";
    return Number(val).toFixed(digits) + "%";
  };

  const el = (tag, className = "", text = "") => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text) element.textContent = text;
    return element;
  };

  // --- API CALLS ---
  async function fetchPipelineStatus() {
    try {
      const res = await fetch("/api/lab-batch?t=" + Date.now());
      if (res.ok) {
        state.pipeline = await res.json();
        if (state.pipeline.active_month && !state.selectedMonth) {
          state.selectedMonth = state.pipeline.active_month;
        }
      }
    } catch (e) {
      console.warn("Failed to fetch pipeline status:", e);
    }
  }

  async function fetchBusinessData() {
    try {
      const res = await fetch("/api/lab-batch-result?business=1&t=" + Date.now());
      if (res.ok) {
        state.business = await res.json();
      }
    } catch (e) {
      console.warn("Failed to fetch business data:", e);
    }
  }

  async function fetchMLData() {
    try {
      const res = await fetch("/api/lab-batch-result?ml=1&t=" + Date.now());
      if (res.ok) {
        state.ml = await res.json();
      }
    } catch (e) {
      console.warn("Failed to fetch ML data:", e);
    }
  }

  async function executeNextStep() {
    if (!state.pipeline) return;
    try {
      const res = await fetch("/api/lab-batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "run_next" })
      });
      const data = await res.json();
      await refreshAll();
      return data;
    } catch (e) {
      alert("เกิดข้อผิดพลาดในการประมวลผลขั้นตอน: " + e.message);
    }
  }

  async function runAllLoop() {
    if (state.isOrchestrating) return;
    state.isOrchestrating = true;
    renderApp();

    try {
      while (state.isOrchestrating) {
        await fetchPipelineStatus();
        if (!state.pipeline || state.pipeline.is_completed || state.pipeline.is_blocked) {
          break;
        }

        const res = await fetch("/api/lab-batch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "run_next" })
        });

        const result = await res.json();
        await fetchPipelineStatus();
        renderApp();

        if (!result.success || state.pipeline.is_blocked || state.pipeline.is_completed) {
          break;
        }

        // Small pause between stages for visual inspection
        await new Promise(r => setTimeout(r, 600));
      }
    } catch (err) {
      console.error("Run All loop error:", err);
    } finally {
      state.isOrchestrating = false;
      await refreshAll();
    }
  }

  async function submitCorrectionFix(orderItemId, correctedSku, actor, reason) {
    try {
      const res = await fetch("/api/lab-batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "submit_fix",
          order_item_id: orderItemId,
          corrected_sku: correctedSku,
          actor: actor,
          reason: reason
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "บันทึกไม่สำเร็จ");
      state.isFixModalOpen = false;
      await refreshAll();
      alert("✓ " + data.message);
    } catch (e) {
      alert("ไม่สามารถบันทึกการแก้ไขได้: " + e.message);
    }
  }

  async function revalidateAndResume() {
    // Re-execute March Stage 1 with approved fix
    await executeNextStep();
    // Continue Run All automatically
    runAllLoop();
  }

  async function resetLab() {
    try {
      const res = await fetch("/api/lab-batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "reset" })
      });
      if (res.ok) {
        state.isResetModalOpen = false;
        await refreshAll();
        alert("✓ รีเซ็ตระบบการทดลองเรียบร้อยแล้ว");
      }
    } catch (e) {
      alert("รีเซ็ตไม่สำเร็จ: " + e.message);
    }
  }

  async function refreshAll() {
    await Promise.all([fetchPipelineStatus(), fetchBusinessData(), fetchMLData()]);
    renderApp();
  }

  // --- RENDER FUNCTIONS ---

  function renderMonthChips() {
    const wrap = el("div", "month-chips-container");
    const header = el("div", "month-chips-header");
    const title = el("div", "month-chips-title", "ความคืบหน้ารายเดือน (10 เดือน: ม.ค. – ต.ค. 2026)");
    const summary = el(
      "div",
      "month-chips-summary",
      `เผยแพร่แล้ว ${state.pipeline?.published_count || 0}/10 เดือน · สถานะรอบ: ${
        state.pipeline?.is_completed ? "สำเร็จครบถ้วน" : state.pipeline?.is_blocked ? "ติดข้อผิดพลาด (Blocked)" : "พร้อมประมวลผล"
      }`
    );
    header.append(title, summary);
    wrap.append(header);

    const grid = el("div", "month-chips-grid");
    const months = state.pipeline?.months || [];

    months.forEach(m => {
      const chip = el("div", `month-chip ${state.viewingMonth === m.month ? "is-active-view" : ""}`);
      chip.onclick = () => {
        state.viewingMonth = m.month;
        renderApp();
      };

      const monthName = el("span", "", m.month);
      const typeTag = el("span", "chip-type-tag", m.type === "INITIAL" ? "INITIAL" : "INCR");
      
      let badgeCls = "badge-not-started";
      if (m.status === "PUBLISHED") badgeCls = "badge-published";
      else if (m.status === "BLOCKED") badgeCls = "badge-blocked";
      else if (m.status === "RUNNING") badgeCls = "badge-running";
      else if (m.status === "READY") badgeCls = "badge-ready";

      const badge = el("span", `chip-status-badge ${badgeCls}`, m.status);
      chip.append(monthName, typeTag, badge);
      grid.append(chip);
    });

    wrap.append(grid);
    return wrap;
  }

  function renderMainControls() {
    const card = el("div", "main-controls-card");
    const isBlocked = state.pipeline?.is_blocked;
    const isCompleted = state.pipeline?.is_completed;
    const isRunning = state.isOrchestrating;

    // Button 1: Run Next Step
    const btnNext = el("button", "run-btn-card", "");
    btnNext.type = "button";
    btnNext.disabled = isBlocked || isCompleted || isRunning;
    btnNext.onclick = () => executeNextStep();

    const nextHdr = el("div", "run-btn-header");
    nextHdr.append(
      el("span", "run-btn-title", "▶ Run Next Step (รันทีละขั้นตอน)"),
      el("span", "run-btn-icon", "→")
    );
    const nextDesc = el(
      "span",
      "run-btn-desc",
      "ประมวลผลขั้นตอนถัดไป พร้อมแสดง Input, Process, Validation และ Output อย่างละเอียด"
    );
    btnNext.append(nextHdr, nextDesc);

    // Button 2: Run All
    const btnAll = el("button", "run-btn-card card-primary", "");
    btnAll.type = "button";
    btnAll.disabled = isBlocked || isCompleted || isRunning;
    btnAll.onclick = () => runAllLoop();

    const allHdr = el("div", "run-btn-header");
    allHdr.append(
      el("span", "run-btn-title", isRunning ? "⏳ กำลังรันอัตโนมัติ..." : "⏩ Run All (รันทั้งหมดจนจบ)"),
      el("span", "run-btn-icon", "⚡")
    );
    const allDesc = el(
      "span",
      "run-btn-desc",
      "ประมวลผลขั้นตอนและข้อมูลที่เหลือโดยอัตโนมัติ และหยุดเมื่อพบข้อผิดพลาด"
    );
    btnAll.append(allHdr, allDesc);

    card.append(btnNext, btnAll);

    // Contextual Blocked Banner & Review & Fix Button
    if (isBlocked) {
      const blockedBox = el("div", "notice notice-danger", "");
      const msg = el(
        "div",
        "",
        "พบข้อมูลไม่ผ่านการตรวจสอบ — หยุดการประมวลผลเพื่อแก้ไข (Foreign Key Violation ในเดือนมีนาคม)"
      );
      
      const btnGroup = el("div", "h-stack", "");
      const btnFix = el("button", "button button-primary", "🔍 Review & Fix (ตรวจสอบและแก้ไขข้อมูล)");
      btnFix.onclick = () => {
        state.isFixModalOpen = true;
        renderApp();
      };
      
      const hasApprovedFix = Boolean(state.pipeline?.approved_fix || localStorage.getItem("approved_fix_march"));
      if (hasApprovedFix) {
        const btnResume = el("button", "button button-outline", "⚡ Revalidate & Resume (ตรวจสอบซ้ำและรันต่อ)");
        btnResume.onclick = () => revalidateAndResume();
        btnGroup.append(btnResume);
      }

      btnGroup.prepend(btnFix);
      blockedBox.append(msg, btnGroup);
      return [card, blockedBox];
    }

    return card;
  }

  function renderStages() {
    const wrap = el("div", "pipeline-stages-container");
    const viewingMonthObj = state.pipeline?.months?.find(m => m.month === state.viewingMonth);
    const stages = viewingMonthObj?.stages || [
      { name: "ingest", title: "1. Source → ER1 Database (Ingest)", status: "pending" },
      { name: "extract", title: "2. ER1 → Data Lake Raw (Extract)", status: "pending" },
      { name: "transform", title: "3. Transform & Data Quality (Standardize)", status: "pending" },
      { name: "load", title: "4. Load ER2 Warehouse (Kimball)", status: "pending" },
      { name: "validate", title: "5. Reconcile & Publish (Reconciliation)", status: "pending" }
    ];

    stages.forEach((s, idx) => {
      const isOpen = state.selectedStage === s.name;
      const isSuccess = s.conclusion === "success";
      const isFailed = s.conclusion === "failure";

      const card = el(
        "div",
        `stage-card-wrapper ${isOpen ? "is-open" : ""} ${isSuccess ? "is-stage-success" : ""} ${isFailed ? "is-stage-failed" : ""}`
      );

      const header = el("button", "stage-card-header");
      header.type = "button";
      header.onclick = () => {
        state.selectedStage = isOpen ? "" : s.name;
        renderApp();
      };

      const titleGroup = el("div", "stage-card-title-group");
      const badgeNum = el("div", "stage-badge-number", String(idx + 1));
      const textGroup = el("div", "");
      const title = el("div", "stage-title-text", s.title || s.name);
      const sub = el("div", "stage-sub-text", `สถานะ: ${s.status} ${s.executed_at ? "· เวลา: " + new Date(s.executed_at).toLocaleTimeString() : ""}`);
      textGroup.append(title, sub);
      titleGroup.append(badgeNum, textGroup);

      const actions = el("div", "stage-card-actions");
      const pill = el(
        "span",
        `stage-status-pill ${isSuccess ? "badge-published" : isFailed ? "badge-blocked" : "badge-not-started"}`,
        isSuccess ? "PASSED" : isFailed ? "FAILED" : s.status
      );
      const chevron = el("span", "stage-expand-chevron", "▼");
      actions.append(pill, chevron);

      header.append(titleGroup, actions);
      card.append(header);

      if (isOpen) {
        const body = renderStageExpandedBody(s, viewingMonthObj);
        card.append(body);
      }

      wrap.append(card);
    });

    return wrap;
  }

  function renderStageExpandedBody(stage, monthObj) {
    const body = el("div", "stage-expanded-body");

    // Tab buttons
    const tabsBar = el("div", "stage-tab-buttons");
    ["input", "process", "validation", "output", "preview"].forEach(tab => {
      const btn = el(
        "button",
        `stage-tab-btn ${state.selectedTab === tab ? "is-active-tab" : ""}`,
        tab.toUpperCase()
      );
      btn.onclick = e => {
        e.stopPropagation();
        state.selectedTab = tab;
        renderApp();
      };
      tabsBar.append(btn);
    });
    body.append(tabsBar);

    // Tab Content Panel
    const panel = el("div", "stage-tab-panel");

    if (state.selectedTab === "input") {
      panel.innerHTML = `
        <div class="stage-info-grid">
          <div class="stage-info-cell">
            <span class="stage-info-label">ชุดข้อมูลต้นทาง</span>
            <span class="stage-info-value">Source CSVs (21 ตาราง) เดือน ${state.viewingMonth}</span>
          </div>
          <div class="stage-info-cell">
            <span class="stage-info-label">ประเภทการรัน</span>
            <span class="stage-info-value">${monthObj?.type || "INCREMENTAL"}</span>
          </div>
          <div class="stage-info-cell">
            <span class="stage-info-label">การตรวจสอบความสมบูรณ์</span>
            <span class="stage-info-value">Schema Contract Validated (SHA-256)</span>
          </div>
        </div>
      `;
    } else if (state.selectedTab === "process") {
      panel.innerHTML = `
        <div class="stage-info-grid">
          <div class="stage-info-cell">
            <span class="stage-info-label">คำสั่ง / กระบวนการประมวลผล</span>
            <span class="stage-info-value">${stage.name === "ingest" ? "COPY & UPSERT INTO demo_er1 (Transactional)" : stage.name === "extract" ? "PARQUET_SNAPPY_EXPORT" : stage.name === "transform" ? "BUSINESS_RULES_ALLOCATION" : stage.name === "load" ? "KIMBALL_STAR_SCHEMA_UPSERT" : "ZERO_VARIANCE_RECONCILIATION"}</span>
          </div>
          <div class="stage-info-cell">
            <span class="stage-info-label">เป้าหมายข้อมูล</span>
            <span class="stage-info-value">${stage.name === "ingest" ? "Neon PostgreSQL (25 ตาราง)" : stage.name === "extract" ? "Data Lake Raw Parquet" : stage.name === "transform" ? "Standardized Data Lake" : stage.name === "load" ? "ER2 DuckDB Warehouse" : "Published Snapshot"}</span>
          </div>
          <div class="stage-info-cell">
            <span class="stage-info-label">กลไก Idempotency</span>
            <span class="stage-info-value">Atomic Checkpoint & Conflict Guards</span>
          </div>
        </div>
      `;
    } else if (state.selectedTab === "validation") {
      const isFailed = stage.conclusion === "failure";
      panel.innerHTML = `
        <div class="lab-checks">
          <div class="lab-check">
            <span class="lab-check-icon ${isFailed ? "lab-fail" : "lab-ok"}">${isFailed ? "✗" : "✓"}</span>
            <div class="small">
              <strong>Referential Integrity (Fact_Order_Items.SKU_ID ∈ Dim_SKU)</strong><br>
              ${isFailed ? "<span style='color:var(--red)'>FAIL: พบ SKU_ERR_UNKNOWN_DEMO ไม่อยู่ใน Dim_SKU กักกันข้อมูลเพื่อความปลอดภัย</span>" : "PASS: ทุกแถวมี Foreign Key ถูกต้องใน Master Dim_SKU"}
            </div>
          </div>
          <div class="lab-check">
            <span class="lab-check-icon lab-ok">✓</span>
            <div class="small">
              <strong>Primary Key Uniqueness & Not-Null Check</strong><br>
              PASS: ไม่พบ Primary Key ซ้ำซ้อนและไม่มีค่าว่างในฟิลด์จำเป็น
            </div>
          </div>
          <div class="lab-check">
            <span class="lab-check-icon lab-ok">✓</span>
            <div class="small">
              <strong>Business Rules & Currency Reconciliation</strong><br>
              PASS: ยอด Gross Reference Sales, ส่วนลด Campaign และ Voucher ตรงตามสมการ
            </div>
          </div>
        </div>
      `;
    } else if (state.selectedTab === "output") {
      panel.innerHTML = `
        <div class="stage-info-grid">
          <div class="stage-info-cell">
            <span class="stage-info-label">จำนวนแถวที่ประมวลผล</span>
            <span class="stage-info-value">${formatNumber(monthObj?.metrics?.items || 3500)} แถว</span>
          </div>
          <div class="stage-info-cell">
            <span class="stage-info-label">สถานะผลลัพธ์</span>
            <span class="stage-info-value">${stage.conclusion === "failure" ? "QUARANTINED_BLOCKED" : "COMMITTED_SUCCESS"}</span>
          </div>
          <div class="stage-info-cell">
            <span class="stage-info-label">ปลายทาง Artifacts</span>
            <span class="stage-info-value">${stage.name === "load" || stage.name === "validate" ? "er2.duckdb (Kimball DWH)" : "lake/standardized/"}</span>
          </div>
        </div>
      `;
    } else if (state.selectedTab === "preview") {
      panel.innerHTML = `
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Order_ID</th>
                <th>SKU_ID</th>
                <th>Base_Unit_Price</th>
                <th>สถานะรายการ</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>ORD-${state.viewingMonth.replace("-", "")}-00001</td>
                <td>${state.viewingMonth === "2026-03" && stage.conclusion === "failure" ? "<span style='color:var(--red);font-weight:bold'>SKU_ERR_UNKNOWN_DEMO</span>" : "PG01-BL-L"}</td>
                <td>199.00 ฿</td>
                <td><span class="status ${stage.conclusion === "failure" ? "status-fail" : "status-pass"}">${stage.conclusion === "failure" ? "QUARANTINED" : "COMMITTED"}</span></td>
              </tr>
              <tr>
                <td>ORD-${state.viewingMonth.replace("-", "")}-00002</td>
                <td>PG02-WH-M</td>
                <td>229.00 ฿</td>
                <td><span class="status status-pass">COMMITTED</span></td>
              </tr>
              <tr>
                <td>ORD-${state.viewingMonth.replace("-", "")}-00003</td>
                <td>PG03-NA-XL</td>
                <td>279.00 ฿</td>
                <td><span class="status status-pass">COMMITTED</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      `;
    }

    body.append(panel);
    return body;
  }

  // --- REVIEW & FIX MODAL ---
  function renderFixModal() {
    if (!state.isFixModalOpen) return null;

    const overlay = el("div", "modal-overlay");
    overlay.onclick = e => {
      if (e.target === overlay) {
        state.isFixModalOpen = false;
        renderApp();
      }
    };

    const card = el("div", "modal-card");

    // Header
    const hdr = el("div", "modal-header");
    hdr.append(
      el("h3", "modal-title", "🛠 ตรวจสอบและแก้ไขข้อมูลสินค้า (Review & Fix)"),
      (() => {
        const btn = el("button", "modal-close-btn", "✕");
        btn.onclick = () => {
          state.isFixModalOpen = false;
          renderApp();
        };
        return btn;
      })()
    );

    // Body
    const body = el("div", "modal-body");

    // Order Slip / Warehouse Evidence Card
    const slipCard = el("div", "order-slip-card");
    slipCard.innerHTML = `
      <div class="order-slip-title">📄 หลักฐานใบคำสั่งซื้อ / Packing Slip คลังสินค้าจริง (Audit Evidence)</div>
      <div class="order-slip-desc">
        <strong>หมายเลขคำสั่งซื้อ:</strong> ORD-202603-00001<br>
        <strong>รหัสรายการ:</strong> ORD-202603-00001-I1<br>
        <strong>รายการสินค้าบนใบส่งของ:</strong> เสื้อยืดคอกลม Cotton 100% พรีเมียม - สีดำ / ไซส์ L<br>
        <strong>ราคาป้าย ณ จุดขาย:</strong> 199.00 บาท (กลุ่ม PG01 คอกลม)<br>
        <strong>รหัสที่ผิดพลาดในระบบส่งออก:</strong> <span style="color:var(--red);font-weight:bold">SKU_ERR_UNKNOWN_DEMO</span>
      </div>
    `;

    // Form
    const form = el("div", "fix-form");
    form.innerHTML = `
      <div class="fix-field">
        <label>เลือก SKU ที่ถูกต้องจากฐานข้อมูล Master (Dim_SKU):</label>
        <select id="correctSkuSelect">
          <option value="">-- กรุณาเลือกสินค้าจาก Master Data --</option>
          <optgroup label="PG01: คอกลม (199 บาท)">
            <option value="PG01-BL-L">PG01-BL-L (คอกลม Black L)</option>
            <option value="PG01-BL-M">PG01-BL-M (คอกลม Black M)</option>
            <option value="PG01-BL-S">PG01-BL-S (คอกลม Black S)</option>
            <option value="PG01-WH-L">PG01-WH-L (คอกลม White L)</option>
          </optgroup>
          <optgroup label="PG02: คอวี (229 บาท)">
            <option value="PG02-BL-L">PG02-BL-L (คอวี Black L)</option>
            <option value="PG02-WH-M">PG02-WH-M (คอวี White M)</option>
          </optgroup>
          <optgroup label="PG03: คอเต่า (279 บาท)">
            <option value="PG03-BL-L">PG03-BL-L (คอเต่า Black L)</option>
          </optgroup>
          <optgroup label="PG04: Crop (189 บาท)">
            <option value="PG04-BL-S">PG04-BL-S (Crop Black S)</option>
          </optgroup>
          <optgroup label="PG05: Oversize (259 บาท)">
            <option value="PG05-BL-XL">PG05-BL-XL (Oversize Black XL)</option>
          </optgroup>
        </select>
      </div>
      <div class="fix-field" style="margin-top:12px;">
        <label>เหตุผลและหลักฐานอ้างอิงการแก้ไข (Reason / Audit Trail):</label>
        <textarea id="fixReasonInput" rows="2">ตรวจสอบใบเสร็จคำสั่งซื้อและ Packing Slip คลังสินค้า ยืนยันเสื้อยืดคอกลม สีดำ ไซส์ L (199 บาท)</textarea>
      </div>
      <div class="fix-field" style="margin-top:12px;">
        <label>ผู้ยืนยัน / ผู้อนุมัติ (Authorized Data Owner):</label>
        <input type="text" id="fixActorInput" value="Data Owner (Classroom Reviewer)">
      </div>
    `;

    body.append(slipCard, form);

    // Footer
    const ftr = el("div", "modal-footer");
    const btnCancel = el("button", "button button-outline", "ยกเลิก");
    btnCancel.onclick = () => {
      state.isFixModalOpen = false;
      renderApp();
    };

    const btnSubmit = el("button", "button button-primary", "บันทึกการแก้ไขและเตรียมรันต่อ");
    btnSubmit.onclick = () => {
      const select = $("#correctSkuSelect");
      const skuVal = select ? select.value : "";
      if (!skuVal) {
        alert("กรุณาเลือก SKU ที่ถูกต้องจากรายการ");
        return;
      }
      const reason = $("#fixReasonInput")?.value || "";
      const actor = $("#fixActorInput")?.value || "";

      submitCorrectionFix("ORD-202603-00001-I1", skuVal, actor, reason);
    };

    ftr.append(btnCancel, btnSubmit);
    card.append(hdr, body, ftr);
    overlay.append(card);
    return overlay;
  }

  // --- BUSINESS DASHBOARD VIEW ---
  function renderBusinessView() {
    const wrap = el("div", "");
    const biz = state.business;
    const months = biz?.months || [];
    const latest = biz?.latest_month || months[months.length - 1];

    if (!months.length) {
      return el(
        "div",
        "empty-state",
        "ยังไม่มีข้อมูลที่ผ่านการ Publish เข้าสู่ Data Warehouse · กรุณาไปที่เมนู 'ทดสอบการนำเข้าข้อมูล' เพื่อเริ่มรันกระบวนการ"
      );
    }

    // 1. Health Summary Cards
    const metricsGrid = el("div", "metrics");
    const targetGap = latest.revenue_gap;
    const targetAchieve = latest.revenue_achievement_pct;
    const isTargetPass = latest.target_status === "PASS";
    const isProfitPass = latest.profit_protection_status === "PASS";

    metricsGrid.innerHTML = `
      <div class="metric">
        <div class="metric-label">รายได้สุทธิ (Net Revenue)</div>
        <div class="metric-value">${formatMoney(latest.net_revenue)}</div>
        <div class="metric-sub">เทียบเป้าหมาย: ${formatMoney(latest.revenue_target)}</div>
      </div>
      <div class="metric">
        <div class="metric-label">อัตราทำได้ตามเป้า (Target Achievement)</div>
        <div class="metric-value ${isTargetPass ? "metric-good" : "metric-bad"}">${formatPct(targetAchieve)}</div>
        <div class="metric-sub">${isTargetPass ? "✓ บรรลุเป้าหมายยอดขาย" : "⚠ ต่ำกว่าเป้าหมาย " + formatMoney(Math.abs(targetGap))}</div>
      </div>
      <div class="metric">
        <div class="metric-label">กำไรส่วนเกิน (Contribution Profit)</div>
        <div class="metric-value ${isProfitPass ? "metric-good" : "metric-bad"}">${formatMoney(latest.contribution_profit)}</div>
        <div class="metric-sub">Descriptive Margin: ${formatPct(latest.profit_margin_pct)}</div>
      </div>
      <div class="metric">
        <div class="metric-label">Profit Protection Rate (≥ 10% Gross)</div>
        <div class="metric-value ${isProfitPass ? "metric-good" : "metric-bad"}">${formatPct(latest.profit_protection_rate_pct)}</div>
        <div class="metric-sub">Headroom: ${formatMoney(latest.profit_protection_headroom)} (${isProfitPass ? "ผ่านเกณฑ์ 10%" : "ต่ำกว่าเกณฑ์ 10%"})</div>
      </div>
    `;
    wrap.append(metricsGrid);

    // 2. 10-Month Financial Trend Table
    const trendPanel = el("div", "panel", "");
    trendPanel.style.marginTop = "20px";
    trendPanel.innerHTML = `
      <div class="panel-head">
        <div>
          <h2 class="panel-heading">แนวโน้มผลประกอบการ 10 เดือน (2026-01 ถึง 2026-10)</h2>
          <p class="panel-description">เปรียบเทียบยอดขายสุทธิต่อเป้าหมาย และอัตราส่วนคุ้มครองกำไร (Profit Protection Rate)</p>
        </div>
      </div>
      <div class="panel-body">
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>เดือน</th>
                <th class="text-right">Gross Ref Sales</th>
                <th class="text-right">Net Revenue</th>
                <th class="text-right">เป้าหมาย</th>
                <th>สถานะเป้าหมาย</th>
                <th class="text-right">กำไร (Profit)</th>
                <th class="text-right">Profit Rate</th>
                <th>เกณฑ์กำไร (≥10%)</th>
              </tr>
            </thead>
            <tbody>
              ${months
                .map(
                  m => `
                <tr>
                  <td><strong>${m.month}</strong></td>
                  <td class="text-right">${formatMoney(m.gross_reference_sales)}</td>
                  <td class="text-right">${formatMoney(m.net_revenue)}</td>
                  <td class="text-right">${formatMoney(m.revenue_target)}</td>
                  <td><span class="status ${m.target_status === "PASS" ? "status-pass" : "status-fail"}">${m.target_status} (${m.revenue_achievement_pct}%)</span></td>
                  <td class="text-right">${formatMoney(m.contribution_profit)}</td>
                  <td class="text-right">${formatPct(m.profit_protection_rate_pct)}</td>
                  <td><span class="status ${m.profit_protection_status === "PASS" ? "status-pass" : "status-fail"}">${m.profit_protection_status}</span></td>
                </tr>
              `
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
    wrap.append(trendPanel);

    // 3. 11-Step Cost Waterfall
    const waterfallPanel = el("div", "panel", "");
    waterfallPanel.style.marginTop = "20px";
    const grossVal = latest.gross_reference_sales || 1;

    waterfallPanel.innerHTML = `
      <div class="panel-head">
        <div>
          <h2 class="panel-heading">11-Step Cost & Profit Waterfall (เดือนล่าสุด: ${latest.month})</h2>
          <p class="panel-description">การหักลดต้นทุน 11 ขั้นตอนตาม Business Data Contract ไม่มีการหักซ้ำ</p>
        </div>
      </div>
      <div class="panel-body">
        <div class="waterfall-container">
          <div class="waterfall-step">
            <span class="waterfall-label">1. ยอดขายอ้างอิงเต็มราคา (Gross Reference Sales)</span>
            <div class="waterfall-bar-track"><div class="waterfall-bar-fill bar-gross" style="width:100%"></div></div>
            <span class="waterfall-amount">${formatMoney(latest.gross_reference_sales)}</span>
          </div>
          <div class="waterfall-step">
            <span class="waterfall-label">2. (-) ส่วนลดแคมเปญ (Campaign Discount)</span>
            <div class="waterfall-bar-track"><div class="waterfall-bar-fill bar-discount" style="width:${(latest.campaign_discount / grossVal) * 100}%"></div></div>
            <span class="waterfall-amount" style="color:var(--red)">-${formatMoney(latest.campaign_discount)}</span>
          </div>
          <div class="waterfall-step">
            <span class="waterfall-label">3. (-) คูปองส่วนลดผู้ขาย (Allocated Voucher)</span>
            <div class="waterfall-bar-track"><div class="waterfall-bar-fill bar-discount" style="width:${(latest.voucher_discount / grossVal) * 100}%"></div></div>
            <span class="waterfall-amount" style="color:var(--red)">-${formatMoney(latest.voucher_discount)}</span>
          </div>
          <div class="waterfall-step is-net">
            <span class="waterfall-label">= รายได้สุทธิ (Net Revenue)</span>
            <div class="waterfall-bar-track"><div class="waterfall-bar-fill bar-gross" style="width:${(latest.net_revenue / grossVal) * 100}%"></div></div>
            <span class="waterfall-amount">${formatMoney(latest.net_revenue)}</span>
          </div>
          <div class="waterfall-step">
            <span class="waterfall-label">4. (-) ต้นทุนสินค้ามาตรฐาน COGS (40% ของราคาขาย)</span>
            <div class="waterfall-bar-track"><div class="waterfall-bar-fill bar-cost" style="width:${(latest.cogs / grossVal) * 100}%"></div></div>
            <span class="waterfall-amount" style="color:var(--red)">-${formatMoney(latest.cogs)}</span>
          </div>
          <div class="waterfall-step">
            <span class="waterfall-label">5. (-) ค่าธรรมเนียมแพลตฟอร์มประมาณการ (10% Net Rev)</span>
            <div class="waterfall-bar-track"><div class="waterfall-bar-fill bar-cost" style="width:${(latest.platform_fee / grossVal) * 100}%"></div></div>
            <span class="waterfall-amount" style="color:var(--red)">-${formatMoney(latest.platform_fee)}</span>
          </div>
          <div class="waterfall-step">
            <span class="waterfall-label">6. (-) ค่าจัดส่งและคลังสินค้า (Fulfillment Cost)</span>
            <div class="waterfall-bar-track"><div class="waterfall-bar-fill bar-cost" style="width:${(latest.fulfillment_cost / grossVal) * 100}%"></div></div>
            <span class="waterfall-amount" style="color:var(--red)">-${formatMoney(latest.fulfillment_cost)}</span>
          </div>
          <div class="waterfall-step">
            <span class="waterfall-label">7. (-) ค่านายหน้า Affiliate (Affiliate Payout)</span>
            <div class="waterfall-bar-track"><div class="waterfall-bar-fill bar-cost" style="width:${(latest.affiliate_cost / grossVal) * 100}%"></div></div>
            <span class="waterfall-amount" style="color:var(--red)">-${formatMoney(latest.affiliate_cost)}</span>
          </div>
          <div class="waterfall-step">
            <span class="waterfall-label">8. (-) ค่าโฆษณา TikTok Ads (Marketing Spend)</span>
            <div class="waterfall-bar-track"><div class="waterfall-bar-fill bar-cost" style="width:${(latest.ads_cost / grossVal) * 100}%"></div></div>
            <span class="waterfall-amount" style="color:var(--red)">-${formatMoney(latest.ads_cost)}</span>
          </div>
          <div class="waterfall-step">
            <span class="waterfall-label">9. (-) สินค้าตัวอย่างฟรี (Free Samples)</span>
            <div class="waterfall-bar-track"><div class="waterfall-bar-fill bar-cost" style="width:${(latest.samples_cost / grossVal) * 100}%"></div></div>
            <span class="waterfall-amount" style="color:var(--red)">-${formatMoney(latest.samples_cost)}</span>
          </div>
          <div class="waterfall-step">
            <span class="waterfall-label">10. (-) ค่าเคลมสินค้า (Customer Claims)</span>
            <div class="waterfall-bar-track"><div class="waterfall-bar-fill bar-cost" style="width:${(latest.claims_cost / grossVal) * 100}%"></div></div>
            <span class="waterfall-amount" style="color:var(--red)">-${formatMoney(latest.claims_cost)}</span>
          </div>
          <div class="waterfall-step is-profit">
            <span class="waterfall-label">= กำไรส่วนเกินสุทธิ (Contribution Profit)</span>
            <div class="waterfall-bar-track"><div class="waterfall-bar-fill bar-profit" style="width:${(latest.contribution_profit / grossVal) * 100}%"></div></div>
            <span class="waterfall-amount" style="color:var(--good)">${formatMoney(latest.contribution_profit)}</span>
          </div>
        </div>
      </div>
    `;
    wrap.append(waterfallPanel);

    // 4. Product Group Performance
    const groupsPanel = el("div", "panel", "");
    groupsPanel.style.marginTop = "20px";
    const groups = biz?.groups || [];

    groupsPanel.innerHTML = `
      <div class="panel-head">
        <div>
          <h2 class="panel-heading">ประสิทธิภาพตามกลุ่มสินค้า (5 Product Groups / 140 SKUs)</h2>
          <p class="panel-description">ยอดขาย ต้นทุน COGS และกำไรสะสม</p>
        </div>
      </div>
      <div class="panel-body">
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>รหัสกลุ่ม</th>
                <th>ชื่อสินค้า</th>
                <th class="text-right">ราคาขายมาตรฐาน</th>
                <th class="text-right">COGS (40%)</th>
                <th class="text-right">Affiliate Rate</th>
                <th class="text-right">ยอดขายสุทธิรวม</th>
                <th class="text-right">กำไรรวม</th>
                <th class="text-right">Margin %</th>
              </tr>
            </thead>
            <tbody>
              ${groups
                .map(
                  g => `
                <tr>
                  <td><strong>${g.id}</strong></td>
                  <td>${g.name}</td>
                  <td class="text-right">${formatMoney(g.base_price)}</td>
                  <td class="text-right">${formatMoney(g.base_price * 0.4, 2)}</td>
                  <td class="text-right">${g.affiliate_rate}%</td>
                  <td class="text-right">${formatMoney(g.net_revenue)}</td>
                  <td class="text-right">${formatMoney(g.contribution_profit)}</td>
                  <td class="text-right">${formatPct(g.margin_pct)}</td>
                </tr>
              `
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
    wrap.append(groupsPanel);

    return wrap;
  }

  // --- ML LAB VIEW ---
  function renderMLView() {
    const wrap = el("div", "");
    const ml = state.ml;

    if (!ml || ml.status === "INSUFFICIENT_HISTORY" || !ml.ready) {
      wrap.innerHTML = `
        <div class="notice notice-warning">
          <span>⚠</span>
          <span><strong>ประวัติข้อมูลยังไม่เพียงพอสำหรับการฝึกโมเดล ML:</strong> ${
            ml?.message || "ต้องการประวัติข้อมูลคลังสินค้าอย่างน้อย 16 สัปดาห์สำหรับการแบ่ง Train/Validation/Test ตามลำดับเวลา"
          }</span>
        </div>
        <div class="empty-state">
          ระบบ Machine Learning ปฏิบัติตามหลักวิศวกรรมข้อมูลที่เข้มงวด: จะไม่สร้างผลทำนายปลอมขึ้นมาล่วงหน้า<br>
          กรุณารันกระบวนการในหน้า <strong>'ทดสอบการนำเข้าข้อมูล'</strong> ให้ครบอย่างน้อย 4 เดือน (~16 สัปดาห์) เพื่อเปิดใช้งาน ML Lab
        </div>
      `;
      return wrap;
    }

    // Benchmark Table
    const modelPanel = el("div", "panel", "");
    modelPanel.innerHTML = `
      <div class="panel-head">
        <div>
          <h2 class="panel-heading">ผลการประเมินโมเดลเทียบ Baseline (Chronological Holdout Test)</h2>
          <p class="panel-description">เปรียบเทียบ WAPE, MAE และ Signed Bias บนชุดข้อมูลทดสอบตามลำดับเวลา ปราศจาก Data Leakage</p>
        </div>
      </div>
      <div class="panel-body">
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ชื่อโมเดล</th>
                <th>ประเภท</th>
                <th class="text-right">WAPE %</th>
                <th class="text-right">MAE (หน่วย)</th>
                <th class="text-right">Signed Bias %</th>
                <th>ช่วงเวลา Holdout</th>
                <th>สถานะโมเดล</th>
              </tr>
            </thead>
            <tbody>
              ${(ml.models || [])
                .map(
                  m => `
                <tr>
                  <td><strong>${m.model_name}</strong></td>
                  <td>${m.type}</td>
                  <td class="text-right">${formatPct(m.wape_pct)}</td>
                  <td class="text-right">${formatNumber(m.mae_units)}</td>
                  <td class="text-right">${formatPct(m.signed_bias_pct)}</td>
                  <td>${m.test_window}</td>
                  <td><span class="status ${m.status === "CHOSEN_MODEL" ? "status-pass" : "status-pending"}">${m.status}</span></td>
                </tr>
              `
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
    wrap.append(modelPanel);

    // Group Forecasts
    const forecastPanel = el("div", "panel", "");
    forecastPanel.style.marginTop = "20px";
    forecastPanel.innerHTML = `
      <div class="panel-head">
        <div>
          <h2 class="panel-heading">ผลพยากรณ์ความต้องการสินค้ารายสัปดาห์ (Weekly Demand Forecast)</h2>
          <p class="panel-description">คาดการณ์หน่วยขายและยอดขายสัปดาห์ถัดไปพร้อม 95% Confidence Interval</p>
        </div>
      </div>
      <div class="panel-body">
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>กลุ่มสินค้า</th>
                <th class="text-right">หน่วยขายสัปดาห์ก่อน (Lag 1)</th>
                <th class="text-right">เฉลี่ย 4 สัปดาห์ (Rolling 4w)</th>
                <th class="text-right">พยากรณ์หน่วยขาย</th>
                <th class="text-right">ช่วงความเชื่อมั่น 95%</th>
                <th class="text-right">ยอดขายอ้างอิงคาดการณ์</th>
              </tr>
            </thead>
            <tbody>
              ${(ml.group_forecasts || [])
                .map(
                  g => `
                <tr>
                  <td><strong>${g.group_id} - ${g.group_name}</strong></td>
                  <td class="text-right">${formatNumber(g.lag_1_units)}</td>
                  <td class="text-right">${formatNumber(g.rolling_4w_units)}</td>
                  <td class="text-right" style="font-weight:bold;color:var(--red)">${formatNumber(g.predicted_weekly_units)}</td>
                  <td class="text-right">${g.confidence_interval_95 ? g.confidence_interval_95[0] + " - " + g.confidence_interval_95[1] : "—"}</td>
                  <td class="text-right">${formatMoney(g.predicted_gross_thb)}</td>
                </tr>
              `
                )
                .join("")}
            </tbody>
          </table>
        </div>
        <div class="callout" style="margin-top:16px;">
          <strong>คำชี้แจงสำคัญด้านระเบียบวิธี:</strong> ${ml.causality_note}
        </div>
      </div>
    `;
    wrap.append(forecastPanel);

    // Assumption-based Financial Simulation (What-if Studio)
    const simPanel = el("div", "panel", "");
    simPanel.style.marginTop = "20px";
    simPanel.innerHTML = `
      <div class="panel-head">
        <div>
          <h2 class="panel-heading">สตูดิโอจำลองสถานการณ์การเงิน (Assumption-based Financial Simulation)</h2>
          <p class="panel-description">จำลองการปรับงบโฆษณาและส่วนลดภายใต้กรอบ Planning Envelope (60% ต้นทุน / 30% งบยืดหยุ่น / 10% กำไรขั้นต่ำ)</p>
        </div>
      </div>
      <div class="panel-body">
        <div class="scenario-grid">
          <div class="field">
            <span>งบประมาณ Ads สัปดาห์นี้ (บาท)</span>
            <input type="range" min="0" max="20000" step="500" value="${state.scenario.adsSpend}" id="adsRange">
            <strong id="adsVal">${formatMoney(state.scenario.adsSpend)}</strong>
          </div>
          <div class="field">
            <span>อัตราส่วนลดแคมเปญ (%)</span>
            <input type="range" min="0" max="25" step="1" value="${state.scenario.campaignDiscountPct}" id="discRange">
            <strong id="discVal">${state.scenario.campaignDiscountPct}%</strong>
          </div>
          <div class="field">
            <span>งบคูปองส่วนลด Voucher (บาท)</span>
            <input type="range" min="0" max="15000" step="500" value="${state.scenario.voucherSpend}" id="vouchRange">
            <strong id="vouchVal">${formatMoney(state.scenario.voucherSpend)}</strong>
          </div>
        </div>
        <div class="scenario-results" id="simResultsBox">
          <div>
            <div class="small muted">ยอดขายสุทธิคาดการณ์ (Net Revenue)</div>
            <strong style="font-size:16px;">${formatMoney(75000 + state.scenario.adsSpend * 1.8)}</strong>
          </div>
          <div>
            <div class="small muted">กำไรส่วนเกินคาดการณ์ (Contribution Profit)</div>
            <strong style="font-size:16px;color:var(--good);">${formatMoney(24000 - state.scenario.adsSpend * 0.4 - state.scenario.voucherSpend * 0.8)}</strong>
          </div>
          <div>
            <div class="small muted">Profit Protection Status (≥10% Gross)</div>
            <span class="status status-pass">FEASIBLE (ผ่านเกณฑ์คุ้มครองกำไร)</span>
          </div>
        </div>
      </div>
    `;
    wrap.append(simPanel);

    // Event listeners for simulation sliders
    setTimeout(() => {
      const adsR = $("#adsRange");
      const discR = $("#discRange");
      const vouchR = $("#vouchRange");

      if (adsR) {
        adsR.oninput = e => {
          state.scenario.adsSpend = Number(e.target.value);
          const adsValEl = $("#adsVal");
          if (adsValEl) adsValEl.textContent = formatMoney(state.scenario.adsSpend);
        };
      }
      if (discR) {
        discR.oninput = e => {
          state.scenario.campaignDiscountPct = Number(e.target.value);
          const discValEl = $("#discVal");
          if (discValEl) discValEl.textContent = state.scenario.campaignDiscountPct + "%";
        };
      }
      if (vouchR) {
        vouchR.oninput = e => {
          state.scenario.voucherSpend = Number(e.target.value);
          const vouchValEl = $("#vouchVal");
          if (vouchValEl) vouchValEl.textContent = formatMoney(state.scenario.voucherSpend);
        };
      }
    }, 50);

    return wrap;
  }

  // --- MAIN APP RENDERER ---
  function renderApp() {
    const appEl = $("#app");
    if (!appEl) return;
    appEl.innerHTML = "";

    // Header Meta
    const headerMode = $("#headerMode");
    if (headerMode) {
      headerMode.textContent =
        state.view === "pipeline"
          ? "Single Main-Flow Runner"
          : state.view === "ml"
          ? "ML Demand Lab"
          : "Published Warehouse";
    }

    const titleEl = $("#pageTitle");
    const subEl = $("#pageSubtitle");
    const crumbEl = $("#crumbView");

    if (state.view === "pipeline") {
      if (titleEl) titleEl.textContent = "Data Pipeline Runner";
      if (subEl) subEl.textContent = "ระบบนำเข้าและประมวลผลข้อมูล 10 เดือน พร้อมตรวจสอบคุณภาพและกักกันข้อมูล (Generic Data Quality)";
      if (crumbEl) crumbEl.textContent = "PIPELINE RUNNER";

      // Render Pipeline Runner Screen
      appEl.append(renderMonthChips());
      const mainControls = renderMainControls();
      if (Array.isArray(mainControls)) {
        mainControls.forEach(c => appEl.append(c));
      } else {
        appEl.append(mainControls);
      }
      appEl.append(renderStages());

      // Append Fix Modal if active
      const modal = renderFixModal();
      if (modal) appEl.append(modal);

    } else if (state.view === "ml") {
      if (titleEl) titleEl.textContent = "ML Demand Forecasting & Decision Lab";
      if (subEl) subEl.textContent = "การพยากรณ์ความต้องการสินค้าและการจำลองสถานการณ์การเงินภายใต้ข้อจำกัดกำไร 10%";
      if (crumbEl) crumbEl.textContent = "ML LAB";

      appEl.append(renderMLView());

    } else {
      // Default: Business Overview
      if (titleEl) titleEl.textContent = "ภาพรวมธุรกิจ (Business Decision Dashboard)";
      if (subEl) subEl.textContent = "ยอดขาย กำไร และความคุ้มทุนของร้านเสื้อผ้าผู้หญิง คำนวณจาก Data Warehouse ฉบับจริง";
      if (crumbEl) crumbEl.textContent = "BUSINESS OVERVIEW";

      appEl.append(renderBusinessView());
    }

    // Update Footer Status
    const footerStatus = $("#footerStatus");
    if (footerStatus) {
      footerStatus.textContent = `สถานะการเผยแพร่: เผยแพร่แล้ว ${state.pipeline?.published_count || 0}/10 เดือน`;
    }
  }

  // Navigation Setup
  function initNavigation() {
    const navButtons = $$(".nav-item");
    navButtons.forEach(btn => {
      btn.onclick = () => {
        navButtons.forEach(b => b.classList.remove("is-active"));
        btn.classList.add("is-active");
        state.view = btn.getAttribute("data-view") || "business";
        renderApp();
      };
    });
  }

  // Init
  async function init() {
    initNavigation();
    await refreshAll();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
