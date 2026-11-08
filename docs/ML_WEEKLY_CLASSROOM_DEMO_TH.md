# Weekly Forecast MLOps — Demo aligned to classroom learning

## Scope

Goal: show **each real data/ML step** without pretending that a synthetic
sales forecast is validated for real advertising budget decisions.

- Dataset: MOCK TikTok clothing shop, 5 Product Groups, 140 SKUs.
- Existing Data Pipeline: CSV → SQLite Database → Parquet Data Lake → DuckDB Data Warehouse.
- Weekly ML grain: **Product Group × Monday–Sunday week**.
- Forecast issue time: **previous Sunday**.
- Historical features: completed weeks BEFORE that Sunday.
- Future marketing inputs: only synthetic plans with recorded_at before issue time.
- Target: actual Net Product Revenue summed across the 7 target dates, no ads GMV double count.
- Business KPI revenue target and Profit Protection >=10% Gross Reference Sales are kept
  separate and NOT faked or assumed to be forecasted by this model.

## Course lifecycle 8 steps

| Step | Real code / evidence |
| --- | --- |
| 1. Data Extraction | Existing pipeline reads synthetic Source into Database, Lake, DWH |
| 2. EDA | Monthly/group performance CSV in historical source run, input summaries |
| 3. Data Preparation | pipeline/ml_weekly.py builds a strict 28-day history, weekly label and frozen marketing plan |
| 4. Training | Seasonal Naive, LightGBM History, LightGBM Marketing models |
| 5. Evaluation | Rolling Folds (May, June, July 2026) plus locked Aug–Sep test |
| 6. Validation | Model selection by *validation* Group WAPE + baseline comparison; target status reported honestly |
| 7. Serving | Reload saved model from .txt and predict archived test week without reading labels as features |
| 8. Monitoring | After predictions, compare with archived actuals; Group/Shop WAPE alerts as a demo replay |

This is an **offline educational replay**. Live web-serving and production
continuous training are NOT implemented by these scripts.

## Metric clarification

The old daily WAPE = 72.92% cannot be compared directly to **weekly WAPE**.
We compute both separately:

- **Weekly Product Group WAPE** =
  SUM(|prediction for each Group×Week - actual for each Group×Week|)
  / SUM(actual for each Group×Week)
- **Weekly Shop WAPE** =
  SUM(|SUM(group predictions for a week) - SUM(group actuals for that week)|)
  / SUM(actual revenue for all weeks)

Shop WAPE may be smaller because positive and negative group errors cancel.
Both denominators and samples are saved in real evaluation reports.

Illustrative success *targets*:
- Weekly group WAPE <=20%
- Weekly shop WAPE <=15%
These are project goals, not guaranteed accuracy, nor universal standards.

**Never set the WAPE directly**; it comes from actual test predictions.

## Model experiment

Features common to both LightGBM candidates: group, calendar week, lag
weekly revenue, four-week mean/stdev, last-week Ads and discount.

Extra Marketing-Aware features:
- Sum of planned Ads Spend across next 7 dates
- Mean planned Campaign discount percentage for next 7 dates
- Number of planned discount-active days

Marketing-Aware and History LightGBM share the historical features; the only
difference is **additional known future planning inputs**, so the ablation
is interpretable. No causal effect is established.

Split by complete **target week**, never random row:
- Validation 1 train <= April 26; validate May 4–31.
- Validation 2 train <= May 31; validate June 1–28.
- Validation 3 train <= June 28; validate June 29–July 26.
- Locked Test train <= August 2; test August 3–September 27.

The model is chosen using only Validation Group WAPE; the final Test is
not used to tune or select it. Saved model is trained on all available
completed prior weeks.

## Run in Colab or GitHub Actions

    pip install -r requirements-ml.txt
    python -m pytest -q tests/test_ml_weekly.py tests/test_ml_features.py tests/test_ml_history.py
    python -m pipeline.ci_ml_history
    python -m pipeline.ci_ml_weekly_demo

Generated under output/ml_history_ci/main/reports/ml_weekly:
- weekly_training_dataset.parquet — real weekly features and targets
- weekly_rolling_folds.csv, weekly_validation_predictions.csv
- weekly_model_selection.csv
- weekly_test_metrics.csv — Group and Shop WAPE, MAE, Bias, target flags
- weekly_test_by_group.csv — metrics across five Groups
- weekly_test_predictions.csv — Actual vs Forecast by Group/Week/Model
- weekly_feature_importance.csv
- weekly_history_model.txt, weekly_marketing_model.txt
- weekly_model_registry.json — selected model/version/feature order
- serving_replay_predictions.csv — saved model is loaded and re-predicts real inputs
- serving_monitor_replay.json — compare prediction with *later* actual labels
- weekly_backtest_summary.json — machine-readable result for Dashboard

GitHub Actions uploads all files as an artifact for inspection, rather
than fabricating charts and KPIs on frontend.

## Demo talk track

1. "Source ของเราสร้างขึ้นแบบ Synthetic และไหลผ่าน Database, Lake, Warehouse จริง"
2. "Feature Store เก็บ Features ที่ใช้ก่อนวัน Forecast และแผนที่ทราบล่วงหน้า"
3. "เราแบ่งข้อมูลตามเวลาและเทียบ Baseline กับโมเดล ML"
4. "ดู WAPE จริงราย Product Group/ทั้ง Shop เราไม่กำหนด WAPE ล่วงหน้า"
5. "เลือกโมเดลจาก Validation จากนั้นโหลด Model Artifacts ให้ทำนายใหม่"
6. "Monitoring ตรวจเทียบ Prediction กับ Actual แล้วยก Alert หากพลาดเกณฑ์"
7. "นี่คือ MLOps ขั้นทดลอง ไม่ใช่การบอกว่าเพิ่ม Ads แล้วจะมียอดขายเพิ่มจริง"

## Known limitations

- The DWH is a latest-state snapshot; a cut on event_date is not a
  verified historical knowledge/as-of snapshot when late corrections exist.
- The synthetic plans' recorded_at are simulated assumptions, not real history.
- training_ready remains FALSE; model use is DEMO_ONLY_NOT_PRODUCTION.
- A week of future predictions must not use target actual labels. The replay
  accesses actuals ONLY for monitoring after serving.
- A highly accurate synthetic model does not guarantee real TikTok accuracy.
- When budget or discount changes, predictions are associations. Avoid
  claiming causal uplift or guaranteed Profit Protection.
- Phase 4 can connect saved outputs to an interactive Decision Dashboard,
  add logging/monitor tables and governed scenario execution.
