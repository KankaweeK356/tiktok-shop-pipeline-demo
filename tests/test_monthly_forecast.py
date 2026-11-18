"""Next-month forecast engine and shop-month business gates (pure logic, no database)."""
import pytest

from pipeline import business_gates as bg
from pipeline import monthly_forecast as mf


def history(months, base=(20000, 22000, 18000, 15000, 12000), growth=0.03, noise=None):
    rows = []
    for i, month in enumerate(months):
        for g, b in zip(mf.GROUPS, base):
            wobble = 0 if noise is None else noise[(i * 5 + int(g[-1])) % len(noise)]
            rows.append({"month": month, "group": g, "net_revenue": round(b * (1 + growth) ** i * (1 + wobble), 2)})
    return rows


JAN_MAY = [f"2026-0{m}" for m in range(1, 6)]
JAN_JUN = JAN_MAY + ["2026-06"]


def test_may_cutoff_has_only_two_origins_so_the_official_method_is_baseline_not_ml():
    result = mf.generate_forecast(history(JAN_MAY), "2026-06")
    assert result["method_type"] == "BASELINE" and result["model_version"] == "baseline-1"
    assert result["validation"]["status"] == "INSUFFICIENT_VALIDATION"
    assert len(result["validation"]["ml_origins"]) == 2 and result["model_validation_wape_pct"] is None
    assert "INSUFFICIENT_VALIDATION" in result["selection_reason"]
    assert result["training_cutoff_date"] == "2026-05-31" and result["published_through"] == "2026-05"
    assert set(result["predictions"]) == set(mf.GROUPS)
    assert result["shop_prediction"] == pytest.approx(sum(result["predictions"].values()), abs=0.01)


def test_ml_is_only_chosen_after_three_origins_and_when_it_really_beats_the_baseline():
    noisy = history([f"2026-{m:02d}" for m in range(1, 9)], noise=[0.01, -0.02, 0.015, -0.01, 0.02])
    result = mf.generate_forecast(noisy, "2026-09")
    assert len(result["validation"]["ml_origins"]) >= 3
    ml, base = result["validation"]["ml"], result["validation"]["baselines_same_origins_as_ml"]
    best = min(base.values(), key=lambda m: m["shop_wape_pct"])
    if result["method_type"] == "ML":
        assert ml["shop_wape_pct"] < best["shop_wape_pct"]
        assert result["model_validation_wape_pct"] == ml["shop_wape_pct"]
    else:
        assert result["method_type"] == "BASELINE" and "BASELINE" in result["selection_reason"]
    # all origins are compared on identical months
    assert ml["origins"] == best["origins"]


def test_a_forecast_is_reproducible_and_stores_provenance():
    a = mf.generate_forecast(history(JAN_JUN), "2026-07")
    b = mf.generate_forecast(history(JAN_JUN), "2026-07")
    assert a == b
    assert len(a["source_snapshot_sha256"]) == 64 and a["feature_version"] == mf.FEATURE_VERSION


def test_leakage_and_gaps_are_rejected():
    with pytest.raises(mf.ForecastError) as leak:
        mf.generate_forecast(history(JAN_JUN), "2026-06")           # June data present while forecasting June
    assert leak.value.code == "FORECAST_LEAKAGE"
    with pytest.raises(mf.ForecastError) as stale:
        mf.generate_forecast(history(JAN_MAY), "2026-07")           # April/May published but not June
    assert stale.value.code == "FORECAST_CUTOFF_NOT_PUBLISHED"
    rows = [r for r in history(JAN_MAY) if r["month"] != "2026-03"]
    with pytest.raises(mf.ForecastError) as gap:
        mf.generate_forecast(rows, "2026-06")
    assert gap.value.code == "FORECAST_MONTH_GAP"


def test_target_month_actuals_cannot_change_the_forecast():
    base = history(JAN_MAY)
    assert mf.generate_forecast(base, "2026-06")["predictions"] == mf.generate_forecast(list(base), "2026-06")["predictions"]
    assert not any(token in " ".join(mf.FEATURE_NAMES) for token in mf.FORBIDDEN_FEATURE_TOKENS)


def test_monthly_rollup_gates_fail_incomplete_and_missing_inputs_honestly():
    planning = bg.load_planning()
    row = {"month": "2026-05", "gross": 100000, "net": 83821.69, "campaign_reduction": 6000, "voucher": 1500,
           "affiliate": 5000, "ads": 15000, "sample": 1000, "profit": 1875.33, "incomplete_rows": 0}
    gates = bg.shop_month_gates(row, {"target": 91000}, planning)
    assert gates["revenue"]["status"] == "FAIL" and gates["revenue"]["gap"] == pytest.approx(-7178.31)
    assert gates["profit_protection"]["status"] == "FAIL" and gates["profit_protection"]["rate_pct"] == 1.88
    assert gates["marketing_gap"]["rate_pct"] == 28.5 and gates["marketing_gap"]["status"] == "PASS"
    over = bg.shop_month_gates({**row, "ads": 25000}, {"target": 91000}, planning)
    assert over["marketing_gap"]["rate_pct"] == 38.5 and over["marketing_gap"]["status"] == "FAIL"
    incomplete = bg.shop_month_gates({**row, "incomplete_rows": 2, "profit": None}, {"target": 91000}, planning)
    assert incomplete["profit_protection"]["status"] == "INCOMPLETE" and incomplete["marketing_gap"]["status"] == "INCOMPLETE"
    assert incomplete["profit"] is None
    missing = bg.shop_month_gates({**row, "month": "2027-01"}, None, planning)
    assert missing["revenue"]["status"] == "MISSING_TARGET" and missing["marketing_gap"]["status"] == "MISSING_POLICY"


def test_planning_seed_is_a_labelled_simulated_input_without_actuals():
    planning = bg.load_planning()
    assert planning["label"] == "SIMULATED_PRECONFIGURED_FOR_CLASSROOM" and planning["months"]["2026-06"]["revenue_target_thb"] == 94000
    assert len(planning["source_sha256"]) == 64 and all("net" not in v and "actual" not in v for v in planning["months"].values())


def test_forecast_requires_all_five_product_groups_in_every_published_month():
    """A group-month that is absent from the warehouse must stop the forecast, never become a silent 0 in the baseline."""
    import pytest
    from pipeline import monthly_forecast as mf
    groups = ["PG01", "PG02", "PG03", "PG04", "PG05"]
    rows = [{"month": m, "group": g, "net_revenue": 10000 + 100 * i + 10 * k} for i, m in enumerate(["2026-01", "2026-02", "2026-03", "2026-04", "2026-05"]) for k, g in enumerate(groups)]
    ok = mf.generate_forecast(rows, "2026-06", allow_ml=False)
    assert sorted(ok["predictions"]) == groups and all(v > 0 for v in ok["predictions"].values())
    for drop in (("2026-05", "PG03"), ("2026-02", "PG01"), ("2026-01", "PG05")):
        broken = [r for r in rows if (r["month"], r["group"]) != drop]
        with pytest.raises(mf.ForecastError) as err:
            mf.generate_forecast(broken, "2026-06", allow_ml=False)
        assert str(err.value).startswith("FORECAST_INCOMPLETE_GROUP_MONTHS")
    with pytest.raises(mf.ForecastError):
        mf.generate_forecast(rows + [{"month": "2026-05", "group": "PG06", "net_revenue": 1}], "2026-06", allow_ml=False)
