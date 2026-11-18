"""Static contract for the three business tabs (v3 UX package): no fabricated numbers, 4 controls, signed error."""
from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "dashboard" / "app.js").read_text(encoding="utf-8")
SERVER = (Path(__file__).resolve().parents[1] / "lib" / "lab-forecast.js").read_text(encoding="utf-8")


def block(start: str, end: str) -> str:
    return APP[APP.index(start):APP.index(end)]


def test_business_actual_reads_published_er2_and_has_no_fallback_figures():
    biz = block("  // ---- ภาพรวมธุรกิจ (Business Actual)", "  // ---- Published KPI gates")
    assert "state.warehouseSnapshot" in biz and "business?.shop_months" in biz
    for fake in ("88136", "80000", "14.68", "fallbackGroups", "report.json", "Scenario Studio", "Assumed Demand Lift", "baseAds"):
        assert fake not in biz
    assert "Scenario Studio" not in APP and "Assumed Demand Lift" not in APP and "fallbackGroups" not in APP
    assert "getPublishedMonthData" not in APP and "renderScenario" not in APP


def test_forecast_planning_exposes_exactly_four_business_controls_and_no_demand_lift():
    fc = block("  // ---- Forecast & Planning: 3 steps", "  async function loadEvaluationView")
    for key in ('fcControl("ads"', 'fcControl("campaign"', 'fcControl("voucher"', 'fcControl("affiliate"'):
        assert key in fc
    assert fc.count("fcControl(\"") == 4
    for banned in ("cogs_rate_of_base\", \"COGS", "SCENARIO_FIELDS", "Demand Lift", "demand_lift"):
        assert banned not in fc
    for code in ("A:", "B:", "C:"):
        assert code in fc                       # templates are fixed proportions of the reference plan
    assert "fcApplyTemplate(\"A\")" in fc and "mult:" in fc


def test_voucher_unknown_is_never_defaulted_to_zero():
    assert "voucherReference = eligible > 0 ?" in SERVER and ": null;" in SERVER
    fc = block("  // ---- Forecast & Planning: 3 steps", "  async function loadEvaluationView")
    assert "Object.values(f.ctl).some(x => x === null)" in fc        # calculate stays disabled until every control is known


def test_forecast_vs_actual_uses_signed_error_without_good_bad_colouring_and_handles_no_plan():
    ev = block("  function evalBars", "  function setView")
    assert "Actual − Forecast" in ev and "Underforecast" in ev and "Overforecast" in ev
    assert "ไม่มีแผนที่เลือกไว้" in ev and "Execution not verified" in ev
    assert "ยังตัดสินความแม่นยำระยะยาว" in ev and "รอยอดจริง" in ev
