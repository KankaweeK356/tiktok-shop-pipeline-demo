"""Temporal and metric integrity tests for weekly ML demo."""
from datetime import date, timedelta

import pandas as pd
import pytest

from pipeline.ml_weekly import (
    HISTORY_FEATURES, MARKETING_FEATURES, MODELS,
    _score, _score_shop_grouped,
    build_weekly_dataset, split_weekly, train_evaluate_weekly,
)


def example_daily_and_plans(weeks=14):
    start = date(2025, 11, 1)
    until = start + timedelta(days=weeks * 7 + 40)
    data, plans = [], []
    for date_idx in range((until - start).days + 1):
        day = start + timedelta(days=date_idx)
        for group, base in (("PG01", 300), ("PG02", 400)):
            data.append({
                "event_date": day.isoformat(),
                "product_group_id": group,
                "net_revenue": base + 4 * date_idx + (20 if day.weekday() >= 5 else 0),
                "gross_reference_sales": base * 2,
                "campaign_price_reduction": 20.0,
                "ads_cost": 10.0,
            })
            plans.append({
                "scenario_id": "SYNTHETIC_HISTORY_V1",
                "product_group_id": group,
                "plan_date": day.isoformat(),
                "plan_version": 1,
                "planned_ads_spend": 24.0 + date_idx % 5,
                "planned_campaign_discount_rate": 0.1,
                "plan_status": "HISTORICAL",
                "plan_source": "SYNTHETIC_HISTORICAL_PLAN",
                "recorded_at": (
                    day - timedelta(days=35)
                ).isoformat() + "T17:00:00+07:00",
            })
    return pd.DataFrame(data), pd.DataFrame(plans)


def test_full_weeks_unique_and_prediction_timing():
    daily, plans = example_daily_and_plans()
    frame = build_weekly_dataset(
        daily, plans, first_week="2025-12-01", last_week="2026-01-26"
    )
    assert len(frame) == 9 * 2
    assert frame.product_group_id.nunique() == 2
    assert not frame.duplicated(["forecast_week_start", "product_group_id"]).any()
    assert set(frame.history_fidelity) == {"RETROSPECTIVE_LATEST_DWH"}
    assert not frame.training_ready.any()
    row = frame.loc[
        frame.product_group_id.eq("PG01") & frame.forecast_week_start.eq("2025-12-01")
    ].iloc[0]
    assert row.as_of_date == "2025-11-30"
    assert row.forecast_week_end == "2025-12-07"
    # Week previous is Nov 24-30, not a future week.
    expected = daily.loc[
        daily.product_group_id.eq("PG01")
        & daily.event_date.between("2025-11-24", "2025-11-30"),
        "net_revenue",
    ].sum()
    assert row.revenue_last_week == pytest.approx(expected)
    assert row.actual_net_revenue_week > 0
    assert row.planned_ads_week > 0


def test_week_aggregation_can_reduce_error_without_forcing_wape():
    # Opposing signed errors cancel when grouped to shop, not in group WAPE.
    df = pd.DataFrame({
        "forecast_week_start": ["2026-01-05", "2026-01-05"],
        "actual_net_revenue_week": [100.0, 200.0],
        "predicted_net_revenue_week": [125.0, 175.0],
    })
    by_group = _score(df.actual_net_revenue_week, df.predicted_net_revenue_week)
    by_shop = _score_shop_grouped(df)
    assert by_group["wape_pct"] == pytest.approx(16.667, abs=0.001)
    assert by_shop["wape_pct"] == 0.0


def test_change_future_actual_does_not_change_features():
    daily, plans = example_daily_and_plans()
    original = build_weekly_dataset(
        daily, plans, first_week="2025-12-01", last_week="2025-12-08"
    )
    modified = daily.copy()
    modified.loc[modified.event_date.ge("2025-12-08"), "net_revenue"] += 10000
    changed = build_weekly_dataset(
        modified, plans, first_week="2025-12-01", last_week="2025-12-08"
    )
    only_future = ["2025-12-08"]
    first = original.loc[original.forecast_week_start.isin(only_future)]
    second = changed.loc[changed.forecast_week_start.isin(only_future)]
    # As-of for 8 Dec is 7 Dec. All features are still identical.
    assert first[list(MARKETING_FEATURES)].reset_index(drop=True).equals(
        second[list(MARKETING_FEATURES)].reset_index(drop=True)
    )
    assert (first.actual_net_revenue_week != second.actual_net_revenue_week).all()


def test_plan_not_known_asof_is_rejected():
    daily, plans = example_daily_and_plans()
    late = plans.copy()
    late.loc[late.plan_date.eq("2025-12-04"), "recorded_at"] = "2025-12-03T12:00:00+07:00"
    with pytest.raises(ValueError, match="Missing pre-approved"):
        build_weekly_dataset(
            daily, late, first_week="2025-12-01", last_week="2025-12-01"
        )


def test_missing_daily_row_is_rejected_instead_of_filled():
    daily, plans = example_daily_and_plans()
    missing = daily.loc[~(
        daily.product_group_id.eq("PG02") & daily.event_date.eq("2025-12-02")
    )]
    with pytest.raises(ValueError, match="Incomplete daily"):
        build_weekly_dataset(missing, plans, first_week="2025-12-01",
                             last_week="2025-12-01")


def test_target_weeks_not_shared_between_splits():
    daily, plans = example_daily_and_plans()
    frame = build_weekly_dataset(daily, plans, first_week="2025-12-01",
                                 last_week="2026-01-26")
    train, valid = split_weekly(frame, train_end="2026-01-04",
                                valid_start="2026-01-05", valid_end="2026-02-01")
    assert train.forecast_week_start.max() < valid.forecast_week_start.min()
    assert set(train.forecast_week_start).isdisjoint(set(valid.forecast_week_start))
    assert not set(train.product_group_id).isdisjoint(set(valid.product_group_id))


def test_weekly_metric_exact_and_invalid_windows():
    stats = _score([100, 200], [120, 190])
    assert stats["mae_thb_per_week"] == 15.0
    assert stats["wape_pct"] == 10.0
    assert stats["bias_pct"] == pytest.approx(3.333)
    with pytest.raises(ValueError):
        split_weekly(pd.DataFrame(), train_end="2026-05-20",
                     valid_start="2026-05-10", valid_end="2026-06-01")


def test_marketing_ablation_not_identical_columns():
    assert set(HISTORY_FEATURES).issubset(set(MARKETING_FEATURES))
    assert len(set(MARKETING_FEATURES) - set(HISTORY_FEATURES)) == 3
    assert len(MODELS) == 3
