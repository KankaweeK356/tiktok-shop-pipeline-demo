-- TikTok Shop educational project — Feature Store tables (Supabase PostgreSQL).
-- Apply separately in Supabase SQL Editor, NOT inside existing SQLite/DuckDB schemas.
-- Both tables are server-side. Do not expose unrestricted writes to browser clients.
CREATE SCHEMA IF NOT EXISTS ml;

CREATE TABLE IF NOT EXISTS ml.marketing_plan (
  plan_item_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scenario_id TEXT NOT NULL CHECK (length(btrim(scenario_id)) > 0),
  product_group_id TEXT NOT NULL CHECK (length(btrim(product_group_id)) > 0),
  plan_date DATE NOT NULL,
  plan_version INTEGER NOT NULL DEFAULT 1 CHECK (plan_version >= 1),
  planned_ads_spend NUMERIC(14,2) NOT NULL CHECK (planned_ads_spend >= 0),
  planned_campaign_discount_rate NUMERIC(6,4) NOT NULL
    CHECK (planned_campaign_discount_rate BETWEEN 0 AND 1),
  plan_status TEXT NOT NULL CHECK (plan_status IN ('APPROVED','SCENARIO','HISTORICAL')),
  plan_source TEXT NOT NULL CHECK (plan_source IN
    ('USER_SCENARIO','HISTORICAL_PLAN','SYNTHETIC_HISTORICAL_PLAN')),
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (scenario_id, product_group_id, plan_date, plan_version)
);
CREATE INDEX IF NOT EXISTS idx_ml_plan_recorded
    ON ml.marketing_plan (scenario_id, product_group_id, plan_date, recorded_at DESC);

CREATE TABLE IF NOT EXISTS ml.feature_daily (
  feature_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  feature_version TEXT NOT NULL,
  scenario_id TEXT NOT NULL,
  source_run_id TEXT NOT NULL,
  as_of_date DATE NOT NULL,
  forecast_date DATE NOT NULL CHECK (forecast_date > as_of_date),
  product_group_id TEXT NOT NULL,
  forecast_horizon INTEGER NOT NULL CHECK (forecast_horizon BETWEEN 1 AND 90),
  revenue_lag_1d NUMERIC(16,2),
  revenue_lag_7d NUMERIC(16,2),
  revenue_avg_7d NUMERIC(18,6),
  revenue_avg_28d NUMERIC(18,6),
  historical_ads_7d NUMERIC(16,2),
  historical_discount_7d NUMERIC(10,6),
  planned_ads_spend NUMERIC(14,2),
  planned_campaign_discount_rate NUMERIC(6,4),
  plan_version INTEGER,
  plan_item_id UUID REFERENCES ml.marketing_plan(plan_item_id),
  forecast_weekday SMALLINT NOT NULL CHECK (forecast_weekday BETWEEN 0 AND 6),
  target_net_revenue NUMERIC(16,2),
  feature_status TEXT NOT NULL CHECK (feature_status IN
    ('READY','INSUFFICIENT_HISTORY','MISSING_PLAN','NO_GROSS_SALES')),
  history_fidelity TEXT NOT NULL CHECK (history_fidelity IN
    ('POINT_IN_TIME_VERIFIED','RETROSPECTIVE_LATEST_DWH')),
  training_ready BOOLEAN NOT NULL DEFAULT FALSE,
  coverage_note TEXT,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (feature_version, scenario_id, source_run_id, product_group_id, as_of_date, forecast_date),
  CHECK (forecast_horizon = forecast_date - as_of_date),
  CHECK (planned_ads_spend IS NULL OR planned_ads_spend >= 0),
  CHECK (planned_campaign_discount_rate IS NULL OR planned_campaign_discount_rate BETWEEN 0 AND 1),
  CHECK (historical_discount_7d IS NULL OR historical_discount_7d BETWEEN 0 AND 1),
  CHECK (NOT training_ready OR (feature_status='READY' AND target_net_revenue IS NOT NULL
         AND history_fidelity='POINT_IN_TIME_VERIFIED'))
);
CREATE INDEX IF NOT EXISTS idx_ml_feature_time
    ON ml.feature_daily (as_of_date, forecast_date, product_group_id);

ALTER TABLE ml.marketing_plan ENABLE ROW LEVEL SECURITY;
ALTER TABLE ml.feature_daily ENABLE ROW LEVEL SECURITY;
