"""Unit checks for ML temporal splits, labels, plans and metrics."""
from datetime import date, timedelta

import pandas as pd
import pytest

from pipeline.ml_backtest import (
    _metrics, build_training_dataset, split_by_target,
)


def make_data(days=75):
    start = date(2026, 1, 1)
    records = []
    plans = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        for group, base in (("PG01", 150.0), ("PG02", 250.0)):
            records.append({
                "event_date": day.isoformat(), "product_group_id": group,
                "net_revenue": base + offset * 2 + 15 * (day.weekday() == 5),
                "gross_reference_sales": base * 2,
                "campaign_price_reduction": base * 0.10,
                "ads_cost": 10.0 + offset % 5,
            })
            plans.append({
                "scenario_id": "SYNTHETIC_HISTORY_V1",
                "product_group_id": group,
                "plan_date": day.isoformat(),
                "plan_version": 1,
                "planned_ads_spend": 20 + offset % 7,
                "planned_campaign_discount_rate": 0.05,
                "plan_status": "HISTORICAL",
                "plan_source": "SYNTHETIC_HISTORICAL_PLAN",
                "recorded_at": (
                    day - timedelta(days=35)
                ).isoformat() + "T17:00:00+07:00",
            })
    return pd.DataFrame(records), pd.DataFrame(plans)


def make_set(daily=None, plans=None):
    d, p = make_data()
    return build_training_dataset(
        d if daily is None else daily,
        p if plans is None else plans,
        as_of_start="2026-01-29",
        as_of_end="2026-02-06",
        target_last_day="2026-03-10",
        horizon=7,
        source_run_id="unit-test",
    )


def test_multiday_snapshot_unique_and_labels():
    frame = make_set()
    assert len(frame) == 9 * 2 * 7
    keys = ["scenario_id", "as_of_date", "forecast_date", "product_group_id"]
    assert not frame.duplicated(keys).any()
    assert (pd.to_datetime(frame.forecast_date) > pd.to_datetime(frame.as_of_date)).all()
    assert not frame.training_ready.any()
    assert set(frame.history_fidelity) == {"RETROSPECTIVE_LATEST_DWH"}
    assert frame["seasonal_naive_prediction"].ge(0).all()
    assert frame["target_net_revenue"].notna().all()
    row = frame[
        (frame.as_of_date == "2026-02-01") &
        (frame.forecast_date == "2026-02-05") &
        (frame.product_group_id == "PG01")
    ].iloc[0]
    d, _ = make_data()
    reference = d.loc[
        (d.event_date == "2026-01-29") & (d.product_group_id == "PG01")
    ].iloc[0].net_revenue
    assert row.seasonal_naive_prediction == pytest.approx(reference)
    assert row.forecast_horizon == 4


def test_future_actual_revenue_only_changes_labels():
    original_daily, plans = make_data()
    baseline = make_set(original_daily, plans)
    changed = original_daily.copy()
    changed.loc[changed["event_date"] >= "2026-02-07", "net_revenue"] += 5000
    new = make_set(changed, plans)
    view = baseline[baseline.as_of_date == "2026-02-06"].reset_index(drop=True)
    shifted = new[new.as_of_date == "2026-02-06"].reset_index(drop=True)
    features = [
        "revenue_lag_1d", "revenue_lag_7d", "revenue_avg_7d",
        "revenue_avg_28d", "historical_ads_7d", "historical_discount_7d",
        "planned_ads_spend", "planned_campaign_discount_rate",
        "seasonal_naive_prediction",
    ]
    assert view[features].equals(shifted[features])
    assert (view.target_net_revenue != shifted.target_net_revenue).all()


def test_future_recorded_plan_is_not_used():
    d, plans = make_data()
    late = plans.copy()
    late.loc[
        late.plan_date == "2026-02-01", "recorded_at"
    ] = "2026-02-03T00:01:00+07:00"
    base = make_set(d, plans)
    modified = make_set(d, late)
    assert len(modified) < len(base)
    assert not modified.loc[
        (modified.as_of_date == "2026-01-30") &
        (modified.forecast_date == "2026-02-01")
    ].shape[0]


def test_target_date_partition_has_no_cross_fold_overlap():
    data = make_set()
    train, valid = split_by_target(
        data, train_through="2026-02-02",
        validation_from="2026-02-03",
        validation_through="2026-02-13",
    )
    assert train.forecast_date.max() <= "2026-02-02"
    assert valid.forecast_date.min() >= "2026-02-03"
    assert set(train.forecast_date).isdisjoint(set(valid.forecast_date))
    assert train["forecast_horizon"].nunique() > 1


def test_split_date_error_and_metrics():
    data = make_set()
    with pytest.raises(ValueError, match="ordered"):
        split_by_target(
            data, train_through="2026-02-05",
            validation_from="2026-02-04",
            validation_through="2026-02-06",
        )
    got = _metrics([100, 50], [110, 40])
    assert got["mae_thb"] == 10.0
    assert got["wape_pct"] == 13.333
    assert got["bias_pct"] == 0
