-- Reviewed copy of 03_DB/ML_Forecast_and_Scenario_Proposed_v4.sql (Dev Handoff v2). UNCHANGED DDL.
-- NOT APPLIED to any shared Neon database. Apply on a Neon TEST BRANCH first, after Owner approval.
-- Additive only: creates schema demo_ml; touches no demo_er1 / demo_control object.
CREATE SCHEMA IF NOT EXISTS demo_ml;

CREATE TABLE IF NOT EXISTS demo_ml.forecast_run (
    forecast_run_id UUID PRIMARY KEY,
    dataset_key TEXT NOT NULL DEFAULT 'classroom',
    cycle_number INTEGER NOT NULL CHECK (cycle_number > 0),
    target_month DATE NOT NULL,
    training_cutoff_date DATE NOT NULL,
    source_warehouse_run_id UUID NOT NULL,
    source_snapshot_sha256 CHAR(64),
    method_type TEXT NOT NULL CHECK (method_type IN ('ML', 'BASELINE')),
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    feature_version TEXT,
    baseline_validation_wape_pct NUMERIC(12,4),
    model_validation_wape_pct NUMERIC(12,4),
    validation_notes TEXT,
    selection_reason TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sealed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'SEALED')),
    is_official BOOLEAN NOT NULL DEFAULT FALSE,
    created_by TEXT NOT NULL DEFAULT 'CLASSROOM_DEMO',
    CONSTRAINT forecast_month_first_day CHECK (EXTRACT(DAY FROM target_month) = 1),
    CONSTRAINT forecast_cutoff_before_target CHECK (training_cutoff_date < target_month),
    CONSTRAINT official_forecast_is_sealed CHECK (NOT is_official OR (status='SEALED' AND sealed_at IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS forecast_one_official_per_cycle_month
    ON demo_ml.forecast_run(dataset_key, cycle_number, target_month)
    WHERE is_official = TRUE;
CREATE INDEX IF NOT EXISTS forecast_run_target_lookup
    ON demo_ml.forecast_run(dataset_key, cycle_number, target_month, generated_at DESC);

CREATE TABLE IF NOT EXISTS demo_ml.forecast_result (
    forecast_run_id UUID NOT NULL REFERENCES demo_ml.forecast_run(forecast_run_id) ON DELETE RESTRICT,
    product_group_id VARCHAR(20) NOT NULL,
    predicted_net_revenue NUMERIC(18,2) NOT NULL CHECK (predicted_net_revenue >= 0),
    prediction_lower NUMERIC(18,2),
    prediction_upper NUMERIC(18,2),
    PRIMARY KEY (forecast_run_id, product_group_id),
    CONSTRAINT valid_forecast_interval CHECK (
      (prediction_lower IS NULL AND prediction_upper IS NULL) OR
      (prediction_lower IS NOT NULL AND prediction_upper IS NOT NULL AND
       prediction_lower >= 0 AND prediction_lower <= predicted_net_revenue AND
       predicted_net_revenue <= prediction_upper)
    )
);

-- APPLICATION/SERVICE-LEVEL REQUIREMENTS, NOT IMPLEMENTED BY THESE TABLES ALONE:
-- 1. Before sealing, validate exactly five genuine PG01..PG05 groups; sum to shop forecast.
-- 2. Seal only if source_warehouse_run_id points to PUBLISHED cutoff month and
--    all materialized features are dated <= training_cutoff_date.
-- 3. Set only one OFFICIAL run per target month within the same isolated cycle.
-- 4. Once SEALED, prediction fields, provenance and method must be immutable;
--    implement DB triggers or tightly scoped write API + audit tests before production use.
-- 5. In a historical replay, generated_at is real execution time (e.g. Nov 2026);
--    do NOT require generated_at < target_month. Instead verify event ordering:
--    forecast sealed BEFORE target month's actual is INGESTED/PUBLISHED in that cycle.
-- 6. Actual values are queried from versioned PUBLISHED ER2, not copied into ML tables.
-- 7. Comparison must identify the actual warehouse version and evaluation date.
-- 8. No model artifact or feature matrix is stored in forecast tables.
--    Selected plan is stored in demo_ml.scenario_decision. Model artifacts may go to Object Storage.
-- 9. Time/lineage checks need service-side enforcement against the Published Warehouse and Demo Cycle.
-- 10. Before sealing run, verify five valid PG01..PG05 group forecasts.


-- -----------------------------------------------------------------------------
-- One row per explicitly selected plan/version (not each interactive trial)
-- Keep source ER1/ER2 schemas unchanged. Scenario does NOT mutate actual orders.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS demo_ml.scenario_decision (
    scenario_decision_id UUID PRIMARY KEY,
    dataset_key TEXT NOT NULL DEFAULT 'classroom',
    cycle_number INTEGER NOT NULL CHECK (cycle_number > 0),
    target_month DATE NOT NULL,
    decision_version INTEGER NOT NULL CHECK (decision_version >= 1),
    supersedes_decision_id UUID REFERENCES demo_ml.scenario_decision(scenario_decision_id) ON DELETE RESTRICT,
    forecast_run_id UUID NOT NULL REFERENCES demo_ml.forecast_run(forecast_run_id) ON DELETE RESTRICT,
    source_warehouse_run_id UUID NOT NULL,
    approved_target_amount NUMERIC(18,2) NOT NULL CHECK (approved_target_amount > 0),
    target_policy_reference TEXT NOT NULL CHECK (LENGTH(BTRIM(target_policy_reference)) > 0),
    target_policy_sha256 CHAR(64),
    plan_code TEXT NOT NULL CHECK (plan_code IN ('A','B','C','CUSTOM')),
    plan_title TEXT NOT NULL CHECK (LENGTH(BTRIM(plan_title)) > 0),
    decision_reason TEXT NOT NULL CHECK (LENGTH(BTRIM(decision_reason)) > 0),
    selected_by TEXT NOT NULL CHECK (LENGTH(BTRIM(selected_by)) > 0),
    selected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Contains monthly plan by group, e.g. ads budgets, campaign windows/prices,
    -- voucher ORDER-basket rules/eligibility/caps, affiliate rate/attribution mix.
    -- MISSING is represented explicitly, never silently coerced to 0.
    controls_json JSONB NOT NULL CHECK (jsonb_typeof(controls_json) = 'object'),
    -- Volume, basket mix, costs, fulfillment/claim/free sample assumptions,
    -- scenario confidence and lack of execution evidence.
    assumptions_json JSONB NOT NULL CHECK (jsonb_typeof(assumptions_json) = 'object'),
    -- Projected sales/gross/net, contribution profit, GAP, check status,
    -- and the complete formula/denominator version. ASSUMPTIONS, not ML predictions.
    calculated_result_json JSONB NOT NULL CHECK (jsonb_typeof(calculated_result_json) = 'object'),
    calculator_version TEXT NOT NULL CHECK (LENGTH(BTRIM(calculator_version)) > 0),
    CONSTRAINT scenario_target_month_first_day CHECK (EXTRACT(DAY FROM target_month) = 1),
    CONSTRAINT scenario_revision_links CHECK (
      (decision_version = 1 AND supersedes_decision_id IS NULL)
      OR (decision_version > 1 AND supersedes_decision_id IS NOT NULL)
    ),
    CONSTRAINT scenario_unique_version UNIQUE (dataset_key, cycle_number, target_month, decision_version)
);

CREATE INDEX IF NOT EXISTS scenario_decision_lookup
    ON demo_ml.scenario_decision(dataset_key, cycle_number, target_month, decision_version DESC);

-- -----------------------------------------------------------------------------
-- Database immutability safeguards (application service must ALSO validate
-- source published state, target preapproval, group completeness, and order-of-
-- events before accepting these records).
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION demo_ml.forecast_run_seal_guard()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE group_count INTEGER;
DECLARE valid_group_count INTEGER;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status = 'SEALED' THEN
      RAISE EXCEPTION 'SEALED_FORECAST_IMMUTABLE';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status = 'SEALED' THEN
    RAISE EXCEPTION 'SEALED_FORECAST_IMMUTABLE';
  END IF;
  IF NEW.status = 'SEALED' AND OLD.status <> 'SEALED' THEN
    IF NEW.sealed_at IS NULL THEN
      RAISE EXCEPTION 'FORECAST_SEALED_AT_REQUIRED';
    END IF;
    SELECT COUNT(*), COUNT(*) FILTER (WHERE product_group_id IN ('PG01','PG02','PG03','PG04','PG05'))
      INTO group_count, valid_group_count
    FROM demo_ml.forecast_result
    WHERE forecast_run_id = NEW.forecast_run_id;
    IF group_count <> 5 OR valid_group_count <> 5 THEN
      RAISE EXCEPTION 'FORECAST_REQUIRES_EXACTLY_FIVE_GROUPS';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_forecast_run_seal_guard ON demo_ml.forecast_run;
CREATE TRIGGER trg_forecast_run_seal_guard
BEFORE UPDATE OR DELETE ON demo_ml.forecast_run
FOR EACH ROW EXECUTE FUNCTION demo_ml.forecast_run_seal_guard();

CREATE OR REPLACE FUNCTION demo_ml.forecast_result_write_guard()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE linked_status TEXT;
DECLARE linked_run UUID;
BEGIN
  linked_run := CASE WHEN TG_OP = 'DELETE' THEN OLD.forecast_run_id ELSE NEW.forecast_run_id END;
  SELECT status INTO linked_status FROM demo_ml.forecast_run
   WHERE forecast_run_id = linked_run FOR UPDATE;
  IF linked_status = 'SEALED' THEN
    RAISE EXCEPTION 'SEALED_FORECAST_RESULT_IMMUTABLE';
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.forecast_run_id IS DISTINCT FROM NEW.forecast_run_id THEN
    RAISE EXCEPTION 'FORECAST_RESULT_CANNOT_MOVE_RUN';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_forecast_result_write_guard ON demo_ml.forecast_result;
CREATE TRIGGER trg_forecast_result_write_guard
BEFORE INSERT OR UPDATE OR DELETE ON demo_ml.forecast_result
FOR EACH ROW EXECUTE FUNCTION demo_ml.forecast_result_write_guard();

CREATE OR REPLACE FUNCTION demo_ml.scenario_decision_guard()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE pred RECORD;
DECLARE previous_plan RECORD;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'SEALED_SCENARIO_DECISION_IMMUTABLE';
  END IF;
  SELECT status, is_official, dataset_key, cycle_number,
         target_month, source_warehouse_run_id
    INTO pred FROM demo_ml.forecast_run
   WHERE forecast_run_id = NEW.forecast_run_id;
  IF pred.status <> 'SEALED' OR NOT pred.is_official
       OR pred.dataset_key <> NEW.dataset_key
       OR pred.cycle_number <> NEW.cycle_number
       OR pred.target_month <> NEW.target_month
       OR pred.source_warehouse_run_id <> NEW.source_warehouse_run_id THEN
    RAISE EXCEPTION 'SCENARIO_MUST_REFERENCE_MATCHING_OFFICIAL_FORECAST';
  END IF;
  IF NEW.decision_version > 1 THEN
    SELECT dataset_key, cycle_number, target_month, decision_version
      INTO previous_plan FROM demo_ml.scenario_decision
     WHERE scenario_decision_id = NEW.supersedes_decision_id;
    IF NOT FOUND OR previous_plan.dataset_key <> NEW.dataset_key
      OR previous_plan.cycle_number <> NEW.cycle_number
      OR previous_plan.target_month <> NEW.target_month
      OR previous_plan.decision_version <> NEW.decision_version-1 THEN
      RAISE EXCEPTION 'SCENARIO_REVISION_CHAIN_INVALID';
    END IF;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_scenario_decision_guard ON demo_ml.scenario_decision;
CREATE TRIGGER trg_scenario_decision_guard
BEFORE INSERT OR UPDATE OR DELETE ON demo_ml.scenario_decision
FOR EACH ROW EXECUTE FUNCTION demo_ml.scenario_decision_guard();

-- RUNTIME / API GATES NOT ENFORCED HERE; MUST PASS UAT BEFORE MIGRATION:
-- 1. Only create a pre-run Scenario decision if target month's Source ingest has
--    NOT started in this demo cycle; server checks authoritative Neon run state.
-- 2. Read Approved Target from preapproved planning policy with version/hash;
--    do not read unprocessed future transactions or QA/expected_kpi files.
-- 3. Validate controls_json structure, five group coverage where applicable,
--    numeric budget range, voucher per-order eligibility & basket assumptions,
--    affiliate creator-only application; distinguish MISSING from zero.
-- 4. Revisions are inserted before target month Source ingestion; SELECT most
--    recent valid decision_version as the pre-run selected plan. Never overwrite.
-- 5. Forecast remains unchanged on scenario selection; scenario values are user
--    assumptions, not incremental ML prediction.
-- 6. After Actual publish, evaluate Forecast using Published ER2; compare
--    selected-plan spend/financial expectations separately with matching grain.
--    Do not claim that the intended plan was executed nor that it caused growth.
-- 7. Permissions/migrations must be reviewed against actual Neon schema, role
--    privileges, transaction semantics, and current deployed version.
