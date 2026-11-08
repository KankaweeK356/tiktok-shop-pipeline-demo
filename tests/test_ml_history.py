"""Synthetic 12-month ML history: source shape, reproducibility, full pipeline on mini history."""
from datetime import date

import pandas as pd
import pytest

from pipeline.generate_ml_history import generate_ml_history
from pipeline.ml_features import build_feature_rows, read_warehouse_daily
from pipeline.orchestrator import run_batch


def test_history_generated_for_twelve_calendar_months(tmp_path):
    out = tmp_path / "source"
    meta = generate_ml_history(out, seed=8102, base_orders_per_group_day=0.2,
                               n_initial=60, n_incremental=30)
    assert meta["historical_start"] == "2025-11-01"
    assert meta["historical_end"] == "2026-09-30"
    assert meta["historic_monthly_targets"] == 11
    assert meta["historical_ads_rows"] == 334 * 5  # Nov 2025 through Sep 2026
    plans = pd.read_csv(out / "ml_marketing_plan.csv")
    assert plans["product_group_id"].nunique() == 5
    assert plans["plan_date"].min() == "2025-11-01"
    assert plans["plan_date"].max() == "2026-11-01"
    assert not plans.duplicated(["scenario_id", "product_group_id", "plan_date"]).any()
    assert (
        pd.to_datetime(plans["recorded_at"], utc=True).dt.tz_convert("Asia/Bangkok").dt.date
        < pd.to_datetime(plans["plan_date"]).dt.date
    ).all()

    orders = pd.read_csv(out / "initial" / "Fact_Orders.csv")
    assert sum(orders["Order_ID"].str.startswith("OCT")) == 60
    assert sum(orders["Order_ID"].str.startswith("H")) == meta["historical_orders"]
    incremental = pd.read_csv(out / "incremental" / "Fact_Orders.csv")
    assert sum(incremental["Order_ID"].str.startswith("NOV")) == 30
    assert "2026-10" in set(pd.read_csv(
        out / "initial" / "Ref_Business_Target.csv"
    )["Target_Year_Month"])
    assert set(orders.loc[orders["Order_ID"].str.startswith("H"), "Voucher_ID"].dropna()) == set()

    ads = pd.read_csv(out / "initial" / "Fact_Marketing_Costs.csv")
    assert not ads.duplicated(["Record_Date", "Ad_Campaign_ID", "Product_Group_ID"]).any()
    assert ads["Ad_Spend_Amount"].min() >= 0
    bridges = pd.read_csv(out / "initial" / "Bridge_Campaign_Product_Group.csv")
    for group, rows in bridges.groupby("Product_Group_ID"):
        rows = rows.sort_values("Effective_From")
        previous_end = None
        for r in rows.itertuples():
            if previous_end is not None:
                assert previous_end < r.Effective_From, f"Overlapping Campaign: {group}"
            previous_end = r.Effective_To


def test_history_reproducible(tmp_path):
    kwargs = dict(seed=81, start=date(2026, 8, 1), end=date(2026, 8, 31),
                  base_orders_per_group_day=0.5, n_initial=60, n_incremental=30)
    a, b = tmp_path / "a", tmp_path / "b"
    generate_ml_history(a, **kwargs)
    generate_ml_history(b, **kwargs)
    for path in (
        "ml_marketing_plan.csv", "initial/Fact_Orders.csv",
        "initial/Fact_Order_Items.csv", "initial/Fact_Marketing_Costs.csv",
        "initial/Bridge_Campaign_Product_Group.csv",
    ):
        assert (a / path).read_bytes() == (b / path).read_bytes()


def test_history_initial_incremental_and_feature_builder(tmp_path):
    source = tmp_path / "source"
    generate_ml_history(source, seed=901, start=date(2026, 8, 1),
                        end=date(2026, 8, 31),
                        base_orders_per_group_day=0.3,
                        n_initial=60, n_incremental=30)
    workspace = tmp_path / "output" / "mlhistory"
    result = run_batch(workspace, "initial", source)
    assert result["status"] == "SUCCESS"
    assert result["functional_fails"] == 0
    import duckdb
    con = duckdb.connect(str(workspace / "er2.duckdb"), read_only=True)
    try:
        months = {row[0] for row in con.execute(
            'SELECT "Year_Month" FROM "View_Shop_Monthly_KPI"'
        ).fetchall()}
        assert {"2026-08", "2026-10"}.issubset(months)
        assert con.execute(
            'SELECT COUNT(*) FROM "Dim_Date" WHERE "Date_Key"=20260801'
        ).fetchone()[0] == 1
        assert con.execute(
            'SELECT COUNT(*) FROM "Fact_Ads_Daily" WHERE "Date_Key"=20260815'
        ).fetchone()[0] == 5
    finally:
        con.close()
    daily = read_warehouse_daily(workspace / "er2.duckdb")
    plans = pd.read_csv(source / "ml_marketing_plan.csv")
    features = build_feature_rows(
        daily, plans, as_of_date="2026-08-28", horizon_days=2,
        scenario_id="SYNTHETIC_HISTORY_V1", source_run_id="mlhistory-initial"
    )
    assert len(features) == 10
    assert set(features["feature_status"]) == {"READY"}
    assert not features["training_ready"].any()  # latest DWH is not PIT certified

    updated = run_batch(workspace, "incremental", source)
    assert updated["status"] == "SUCCESS"
    assert updated["functional_fails"] == 0
    repeated = run_batch(workspace, "incremental", source)
    assert repeated["status"] == "SUCCESS"
    assert repeated["paid_sales_rows"] == updated["paid_sales_rows"]
    assert repeated["net_revenue"] == updated["net_revenue"]


def test_bad_history_window_fails(tmp_path):
    with pytest.raises(ValueError, match="whole calendar months"):
        generate_ml_history(
            tmp_path / "invalid", start=date(2026, 8, 2),
            end=date(2026, 8, 31)
        )
