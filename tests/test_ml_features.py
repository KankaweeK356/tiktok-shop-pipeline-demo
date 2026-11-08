"""Feature engineering tests: unit tests work without DuckDB; adapter test runs on CI."""
from datetime import date, timedelta

import pandas as pd
import pytest

from pipeline.ml_features import FeatureValidationError, build_feature_rows


def daily_fixture():
    start = date(2026, 10, 1)
    rows = []
    for i in range(42):
        day = start + timedelta(days=i)
        for group, base in (("PG01", 100.0), ("PG02", 200.0)):
            rows.append({
                "event_date": day.isoformat(),
                "product_group_id": group,
                "net_revenue": base + i,
                "gross_reference_sales": 2 * base,
                "campaign_price_reduction": base * 0.2,
                "ads_cost": 10.0,
            })
    return pd.DataFrame(rows)


def plan_fixture():
    return pd.DataFrame([
        {
            "scenario_id": "DEMO", "product_group_id": g,
            "plan_date": day, "plan_version": 1,
            "planned_ads_spend": spend, "planned_campaign_discount_rate": 0.1,
            "plan_status": "HISTORICAL",
            "plan_source": "SYNTHETIC_HISTORICAL_PLAN",
            "recorded_at": "2026-11-01T11:00:00+07:00",
        }
        for day in ("2026-11-02", "2026-11-03")
        for g, spend in (("PG01", 120), ("PG02", 150))
    ])


def build(daily=None, plans=None, **options):
    return build_feature_rows(
        daily_fixture() if daily is None else daily,
        plan_fixture() if plans is None else plans,
        as_of_date="2026-11-01", horizon_days=2,
        scenario_id="DEMO", source_run_id="run-1",
        **options,
    )


def test_grain_lags_rolling_and_label():
    result = build()
    assert len(result) == 4
    assert not result.duplicated(
        ["product_group_id", "as_of_date", "forecast_date", "scenario_id"]
    ).any()
    r = result[
        (result.product_group_id == "PG01")
        & (result.forecast_date == "2026-11-02")
    ].iloc[0]
    assert r.revenue_lag_1d == 131
    assert r.revenue_lag_7d == 124
    assert r.revenue_avg_7d == 128
    assert r.historical_ads_7d == 70
    assert r.historical_discount_7d == pytest.approx(0.1)
    assert r.target_net_revenue == 132
    assert r.forecast_horizon == 1
    assert r.feature_status == "READY"
    assert not r.training_ready


def test_future_actuals_change_labels_not_predictors():
    a = build()
    d = daily_fixture()
    d.loc[d.event_date >= "2026-11-02", "net_revenue"] += 9999
    b = build(daily=d)
    predictors = [
        "revenue_lag_1d", "revenue_lag_7d", "revenue_avg_7d",
        "revenue_avg_28d", "historical_ads_7d", "historical_discount_7d",
    ]
    assert a[predictors].equals(b[predictors])
    assert (a.target_net_revenue != b.target_net_revenue).all()


def test_plan_created_after_cutoff_is_excluded():
    plans = plan_fixture()
    plans.loc[0, "recorded_at"] = "2026-11-02T01:00:00+07:00"
    r = build(plans=plans)
    invisible = r[
        (r.product_group_id == "PG01") & (r.forecast_date == "2026-11-02")
    ].iloc[0]
    assert invisible.feature_status == "MISSING_PLAN"
    assert pd.isna(invisible.planned_ads_spend)


def test_latest_eligible_plan_version():
    p = plan_fixture()
    updated = p.iloc[0].copy()
    updated["plan_version"] = 2
    updated["planned_ads_spend"] = 222
    updated["recorded_at"] = "2026-11-01T15:00:00+07:00"
    p = pd.concat([p, pd.DataFrame([updated])], ignore_index=True)
    r = build(plans=p)
    row = r[
        (r.product_group_id == "PG01") & (r.forecast_date == "2026-11-02")
    ].iloc[0]
    assert row.planned_ads_spend == 222
    assert row.plan_version == 2


def test_invalid_plans_are_rejected():
    p = plan_fixture()
    p.loc[0, "planned_campaign_discount_rate"] = 1.1
    with pytest.raises(FeatureValidationError, match="discount"):
        build(plans=p)
    p = plan_fixture()
    p = pd.concat([p, p.iloc[[0]]], ignore_index=True)
    with pytest.raises(FeatureValidationError, match="Duplicate plan"):
        build(plans=p)


def test_insufficient_history():
    r = build_feature_rows(
        daily_fixture(), plan_fixture(), as_of_date="2026-10-05",
        horizon_days=1, scenario_id="DEMO", source_run_id="run-1",
    )
    assert (r.feature_status == "INSUFFICIENT_HISTORY").all()
    assert not r.training_ready.any()


def test_verified_snapshot_is_required_for_training():
    assert build(history_fidelity="POINT_IN_TIME_VERIFIED").training_ready.all()
    assert not build().training_ready.any()


def test_future_unobserved_date_has_no_label():
    r = build_feature_rows(
        daily_fixture(), plan_fixture(), as_of_date="2026-11-01",
        horizon_days=12, scenario_id="DEMO", source_run_id="run-1",
    )
    assert r[r.forecast_date == "2026-11-11"].target_net_revenue.notna().all()
    assert r[r.forecast_date == "2026-11-12"].target_net_revenue.isna().all()


def test_out_of_range_as_of_rejected():
    with pytest.raises(FeatureValidationError, match="exceeds"):
        build_feature_rows(
            daily_fixture(), plan_fixture(), as_of_date="2026-12-01",
            horizon_days=1, scenario_id="DEMO", source_run_id="run-1",
        )


def test_duckdb_adapter_reads_existing_mart_grain(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    from pipeline.ml_features import read_warehouse_daily
    db = tmp_path / "warehouse.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute('CREATE TABLE "Dim_Date" ("Date_Key" INTEGER, "Full_Date" DATE)')
        con.execute('''CREATE TABLE "Mart_Product_Group_Daily_Performance" (
            "Date_Key" INTEGER, "Product_Group_ID" VARCHAR,
            "Net_Revenue" DOUBLE, "Gross_Reference_Sales" DOUBLE,
            "Campaign_Price_Reduction" DOUBLE, "Ads_Cost" DOUBLE)''')
        con.execute("INSERT INTO Dim_Date VALUES (20261101, DATE '2026-11-01')")
        con.execute(
            "INSERT INTO Mart_Product_Group_Daily_Performance "
            "VALUES (20261101,'PG01',800,1000,100,50)"
        )
    finally:
        con.close()
    out = read_warehouse_daily(db)
    assert len(out) == 1
    assert out.iloc[0]["net_revenue"] == 800
    assert out.iloc[0]["ads_cost"] == 50
