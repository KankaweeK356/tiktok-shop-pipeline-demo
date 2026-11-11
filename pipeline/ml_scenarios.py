"""Saved-model scenario inference at the latest complete historical cutoff.

This is an observational model response, not an estimate of causal ad uplift.
"""
from __future__ import annotations

import calendar
import json
from datetime import timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from .ml_weekly import HISTORY_FEATURES, MARKETING_FEATURES
from .ml_features import read_warehouse_daily


def build_scenarios(warehouse: Path, trained: Path) -> dict:
    registry=json.loads((trained/"weekly_model_registry.json").read_text(encoding="utf-8"))
    daily=read_warehouse_daily(warehouse)
    daily["event_date"]=pd.to_datetime(daily.event_date).dt.date
    groups=sorted(registry["group_encoding"])
    by_group={g:daily.loc[daily.product_group_id.eq(g)].set_index("event_date")
              for g in groups}
    last=max(daily.event_date)
    asof=last-timedelta(days=(last.weekday()+1)%7)
    while asof>min(daily.event_date)+timedelta(days=28):
        window=[asof-timedelta(days=n) for n in range(27,-1,-1)]
        if all(set(window).issubset(set(by_group[g].index)) for g in groups):
            break
        asof-=timedelta(days=7)
    else:
        return {"status":"INSUFFICIENT_COMPLETE_DAILY_HISTORY",
                "reason":"Need 28 consecutive group/day Mart rows at a Sunday cutoff"}
    week=asof+timedelta(days=1)
    selected=registry["selected_model"]
    booster=None
    if selected!="Last Week Naive":
        import lightgbm as lgb
        filename="weekly_history_model.txt" if selected=="LightGBM History" else "weekly_marketing_model.txt"
        booster=lgb.Booster(model_file=str(trained/filename))
    grid=[]
    for group in groups:
        hist=by_group[group].loc[window]
        rev=hist.net_revenue.to_numpy(dtype=float)
        ads=hist.ads_cost.to_numpy(dtype=float)
        gross=hist.gross_reference_sales.to_numpy(dtype=float)
        discount=hist.campaign_price_reduction.to_numpy(dtype=float)
        last4=[float(rev[i:i+7].sum()) for i in (0,7,14,21)]
        reference_budget=round(float(ads[-7:].sum()),2)
        base={"product_group_code":int(registry["group_encoding"][group]),
              "week_of_year":week.isocalendar().week,"week_month":week.month,
              "revenue_last_week":last4[3],"revenue_two_weeks_ago":last4[2],
              "revenue_mean_4weeks":float(np.mean(last4)),
              "revenue_std_4weeks":float(np.std(last4)),
              "historical_ads_last_week":reference_budget,
              "historical_discount_last_week":float(discount[-7:].sum()/gross[-7:].sum())
                  if gross[-7:].sum()>0 else 0.0}
        # These choices are separate versioned plan inputs, never ER1 transaction rows.
        for ratio in (0,0.5,1,1.5,2):
            for campaign_pct in (0,10):
                planned=round(reference_budget*ratio,2)
                feature={**base,"planned_ads_week":planned,
                         "planned_discount_mean_week":campaign_pct/100,
                         "planned_campaign_days":7 if campaign_pct else 0}
                if selected=="Last Week Naive":predicted=last4[3]
                else:
                    columns=HISTORY_FEATURES if selected=="LightGBM History" else MARKETING_FEATURES
                    predicted=float(booster.predict(pd.DataFrame([feature])[list(columns)])[0])
                grid.append({"group_id":group,"budget_ratio":ratio,
                             "planned_ads_week":planned,"campaign_discount_pct":campaign_pct,
                             "predicted_net_revenue_week":round(max(0,predicted),2),
                             "reference_ads_week":reference_budget})
    with duckdb.connect(str(warehouse),read_only=True) as db:
        kpis=dict(db.execute('SELECT Year_Month,Revenue_Target FROM View_Shop_Monthly_KPI').fetchall())
    target=0.0
    for offset in range(7):
        day=week+timedelta(days=offset)
        value=kpis.get(day.strftime("%Y-%m"))
        if value is None:
            target=None;break
        target+=float(value)/calendar.monthrange(day.year,day.month)[1]
    return {"status":"READY","as_of_date":asof.isoformat(),
            "forecast_week_start":week.isoformat(),"forecast_week_end":(week+timedelta(days=6)).isoformat(),
            "selected_model":selected,"model_uses_plan":selected=="LightGBM Marketing",
            "weekly_shop_target":round(target,2) if target is not None else None,
            "grid":grid,
            "limits":["Retrospective cutoff: later actuals may already exist in Warehouse",
                      "Changing a plan input is not a causal Ads/discount effect",
                      "Profit cannot be forecast reliably from this sales-only model"]}
