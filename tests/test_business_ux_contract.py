"""Static contract for the three business tabs (v3 UX package): no fabricated numbers, 4 controls, signed error."""
from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "dashboard" / "app.js").read_text(encoding="utf-8")
SERVER = (Path(__file__).resolve().parents[1] / "lib" / "lab-forecast.js").read_text(encoding="utf-8")


def block(start: str, end: str) -> str:
    return APP[APP.index(start):APP.index(end)]


def test_business_actual_reads_published_er2_and_has_no_fallback_figures():
    biz = block("  // ---- ภาพรวมธุรกิจ (Business Actual)", "adv.append(body); root.append(adv);")
    assert "state.warehouseSnapshot" in biz and "business?.shop_months" in biz
    for fake in ("88136", "80000", "14.68", "fallbackGroups", "report.json", "Scenario Studio", "Assumed Demand Lift", "baseAds"):
        assert fake not in biz
    assert "Scenario Studio" not in APP and "Assumed Demand Lift" not in APP and "fallbackGroups" not in APP
    assert "getPublishedMonthData" not in APP and "renderScenario" not in APP


def test_forecast_planning_v5_is_group_based_live_and_never_autosaves():
    fc = block("  // ---- Forecast & Planning (v5)", "  async function loadEvaluationView")
    for needle in ("fcGroupPanel", "fcVoucherBox", "fcBulkRow", "fcControlsPayload", "fcScheduleCalc", "simSeq", "data-fc-group", "fcReferenceControls", "คืนค่าแผน",
                   "ข้ามแผน", "INSUFFICIENT_HISTORY", "published_months"):
        assert needle in fc
    assert "Calculate" not in fc and "fc-calc" not in fc                     # no manual calculate button: live recalculation
    for banned in ("SCENARIO_FIELDS", "Demand Lift", "demand_lift", "cogs_rate_of_base\", \"COGS"):
        assert banned not in fc
    assert fc.count("sealPlan") == 2 and "addEventListener(\"click\", sealPlan)" in fc      # saved only from the explicit confirm button
    for code in ("A:", "B:", "C:"):
        assert code in fc
    assert "if (seq !== f.simSeq) return;" in fc                              # out-of-order answers are ignored


def test_voucher_unknown_is_never_defaulted_to_zero_and_affiliate_unknown_stays_null():
    fc = block("  // ---- Forecast & Planning (v5)", "  async function loadEvaluationView")
    assert "c.affiliate[g] === null ? null" in fc and "ไม่ทราบ" in fc


def test_forecast_vs_actual_uses_signed_error_without_good_bad_colouring_and_handles_no_plan():
    ev = block("  function evalBars", "  function setView")
    assert "Actual − Forecast" in ev and "Underforecast" in ev and "Overforecast" in ev
    assert "ไม่มีแผนที่เลือกไว้" in ev and "Execution not verified" in ev
    assert "ยังตัดสินความแม่นยำระยะยาว" in ev and "รอยอดจริง" in ev


def test_v4_business_actual_uses_shared_helpers_and_no_hardcoded_month_or_amounts():
    biz = block("  function marketingFrame", "adv.append(body); root.append(adv);")
    assert "window.BusinessInsights" in biz and "groupDrawer" in biz and "ดูรายละเอียด" in biz
    for fake in ("3,174.12", "34,324.80", "37,498.92", "กรกฎาคม", "มิถุนายน", "7.06"):
        assert fake not in biz
    html = (Path(__file__).resolve().parents[1] / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert html.index("business-insights.js") < html.index("app.js")


def test_pipeline_panels_do_not_claim_fixed_results():
    for fake in ("Parity Matched", "88,136", "Certificate SHA-256 generated", "WAPE 8.7%", "6/6 DQ Rules PASS", "1,582", "88806540c4f828fd"):
        assert fake not in APP, fake


def test_every_app_function_that_is_called_is_defined():
    """Guards against deleting a helper that sits between two constants (the Output tab once broke that way)."""
    import re
    called = set(re.findall(r"(?<![.\w])((?:load|render|fc|dq|submit|run|generate|seal|start|refresh|hydrate)[A-Za-z0-9_]*)\(", APP))
    defined = set(re.findall(r"function\s+([A-Za-z0-9_]+)\s*\(", APP)) | set(re.findall(r"(?:const|let|var)\s+([A-Za-z0-9_]+)\s*=", APP))
    defined |= set(re.findall(r"\b([A-Za-z0-9_]+)\s*:\s*(?:async\s*)?\(", APP))                       # callback properties such as renderDetail: (item) => {}
    missing = sorted(n for n in called if n not in defined)
    assert not missing, missing


def test_cleanup_notes_10_to_14_are_in_the_forecast_page():
    fc = block("  // ---- Forecast & Planning (v5)", "  async function loadEvaluationView")
    assert "fc-topbar" in fc and "fc-stickybar" not in fc and "fc-cards" not in fc           # one sticky top bar, no duplicated cards/bottom bar
    assert "fc-stepbtns" not in fc and "custom" not in fc.split("function fcVoucherBox")[1].split("function fcBulkRow")[0]   # no +/- buttons, no custom voucher
    assert "ใช้คูปองที่เลือกได้" in fc and "ต่ำกว่า 10%" in fc and "Margin กลุ่ม" in fc
    assert "คูปอง (ใช้กับทั้งร้าน" in fc and "สัดส่วนออเดอร์ที่ใช้คูปอง" in fc
    for label in ("−10%", "+10%", "−1 จุด", "+1 จุด", "↺ คืนค่าแผน"):
        assert label in fc
