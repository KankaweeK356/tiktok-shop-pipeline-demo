-- PASTE THIS WHOLE FILE INTO THE NEON SQL EDITOR OF THE *TEST BRANCH* (never the main Lab branch).
-- = sql/neon_dq_recovery_migration.sql followed by sql/neon_demo_ml_migration.sql. Additive; touches no demo_er1 data.

-- Data-quality gate, human correction ledger and published-snapshot registry.
--
-- ADDITIVE and IDEMPOTENT. Touches only demo_control metadata: no demo_er1 business
-- table, row, constraint or data is changed. NOT applied automatically: it must be
-- reviewed and applied by the Product Owner on a Neon *test branch first*
-- (see docs/DQ_RECOVERY_RUNBOOK_TH.md). Requires sql/neon_er1_demo_bootstrap.sql.
--
-- Grants: give the lab writer role the same privileges it has on demo_control.pipeline_runs
-- (SELECT, INSERT, UPDATE on the tables below; no DELETE/TRUNCATE is needed or wanted).

BEGIN;

-- 1. Run states: BLOCKED_DQ / READY_TO_RESUME / FAILED_SYSTEM (FAILED stays valid for legacy rows).
DO $status$
DECLARE c TEXT;
BEGIN
  SELECT conname INTO c FROM pg_constraint
   WHERE conrelid='demo_control.pipeline_runs'::regclass AND contype='c'
     AND pg_get_constraintdef(oid) ILIKE '%QUEUED%';
  IF c IS NOT NULL AND c <> 'pipeline_runs_status_check_v2' THEN
    EXECUTE format('ALTER TABLE demo_control.pipeline_runs DROP CONSTRAINT %I', c);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='pipeline_runs_status_check_v2') THEN
    ALTER TABLE demo_control.pipeline_runs ADD CONSTRAINT pipeline_runs_status_check_v2
      CHECK (status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED',
                        'BLOCKED_DQ','READY_TO_RESUME','FAILED_SYSTEM'));
  END IF;
END $status$;

-- 2. Legal run-state transitions (terminal states cannot be re-opened).
CREATE OR REPLACE FUNCTION demo_control.guard_run_status() RETURNS trigger AS $fn$
BEGIN
  IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
       (OLD.status='QUEUED' AND NEW.status IN ('RUNNING','CANCELLED','FAILED','FAILED_SYSTEM'))
    OR (OLD.status='RUNNING' AND NEW.status IN ('SUCCEEDED','FAILED','FAILED_SYSTEM','BLOCKED_DQ','CANCELLED'))
    OR (OLD.status='BLOCKED_DQ' AND NEW.status IN ('READY_TO_RESUME','CANCELLED'))
    OR (OLD.status='READY_TO_RESUME' AND NEW.status IN ('BLOCKED_DQ','CANCELLED'))
  ) THEN
    RAISE EXCEPTION 'Illegal pipeline run transition % -> %', OLD.status, NEW.status
      USING ERRCODE='check_violation';
  END IF;
  RETURN NEW;
END $fn$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_guard_run_status ON demo_control.pipeline_runs;
CREATE TRIGGER trg_guard_run_status BEFORE UPDATE OF status ON demo_control.pipeline_runs
  FOR EACH ROW EXECUTE FUNCTION demo_control.guard_run_status();

-- 3. Rule evaluations (every execution, PASS / FAIL / NOT_CHECKED, with real row counts).
CREATE TABLE IF NOT EXISTS demo_control.dq_rule_result (
 result_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 run_id UUID REFERENCES demo_control.pipeline_runs(run_id),
 dataset_key TEXT NOT NULL DEFAULT 'classroom',
 cycle_number INTEGER NOT NULL CHECK(cycle_number>=1),
 batch TEXT NOT NULL,
 stage_name TEXT NOT NULL CHECK(stage_name IN ('ingest','extract','transform','load','validate')),
 evaluation_kind TEXT NOT NULL CHECK(evaluation_kind IN ('GATE','DEFENSE','REVALIDATION')),
 rule_id TEXT NOT NULL,
 rule_name TEXT NOT NULL,
 rule_kind TEXT NOT NULL CHECK(rule_kind IN ('REFERENCE_EXISTS','NOT_NULL','PK_UNIQUE')),
 input_table TEXT NOT NULL,
 input_column TEXT,
 checked_rows BIGINT NOT NULL CHECK(checked_rows>=0),
 failed_rows BIGINT NOT NULL CHECK(failed_rows>=0),
 threshold NUMERIC NOT NULL DEFAULT 0,
 severity TEXT NOT NULL CHECK(severity IN ('BLOCKING','WARNING')),
 status TEXT NOT NULL CHECK(status IN ('PASS','FAIL','NOT_CHECKED')),
 source_zip_sha256 TEXT CHECK(source_zip_sha256 IS NULL OR source_zip_sha256 ~ '^[0-9a-f]{64}$'),
 source_file TEXT,
 source_file_sha256 TEXT CHECK(source_file_sha256 IS NULL OR source_file_sha256 ~ '^[0-9a-f]{64}$'),
 evidence_uri TEXT,
 correction_set_id TEXT,
 executed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dq_rule_result_run ON demo_control.dq_rule_result(run_id,stage_name);
CREATE INDEX IF NOT EXISTS idx_dq_rule_result_batch ON demo_control.dq_rule_result(dataset_key,cycle_number,batch,executed_at DESC);

-- 4. Durable issues. The original evidence columns are immutable.
CREATE TABLE IF NOT EXISTS demo_control.dq_issue (
 issue_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 issue_key TEXT NOT NULL CHECK(issue_key ~ '^[0-9a-f]{64}$'),
 dataset_key TEXT NOT NULL DEFAULT 'classroom',
 cycle_number INTEGER NOT NULL CHECK(cycle_number>=1),
 batch TEXT NOT NULL,
 first_run_id UUID NOT NULL REFERENCES demo_control.pipeline_runs(run_id),
 last_run_id UUID NOT NULL REFERENCES demo_control.pipeline_runs(run_id),
 rule_id TEXT NOT NULL,
 severity TEXT NOT NULL CHECK(severity IN ('BLOCKING','WARNING')),
 table_name TEXT NOT NULL,
 source_file TEXT NOT NULL,
 source_file_sha256 TEXT CHECK(source_file_sha256 IS NULL OR source_file_sha256 ~ '^[0-9a-f]{64}$'),
 source_zip_sha256 TEXT CHECK(source_zip_sha256 IS NULL OR source_zip_sha256 ~ '^[0-9a-f]{64}$'),
 source_row_no INTEGER,
 pk_json JSONB NOT NULL,
 column_name TEXT,
 invalid_value TEXT,
 parent_table TEXT,
 parent_column TEXT,
 row_snapshot JSONB NOT NULL,
 context JSONB NOT NULL DEFAULT '{}'::jsonb,
 evidence_uri TEXT,
 status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','CORRECTED','REVALIDATED','RESOLVED')),
 resolved_run_id UUID REFERENCES demo_control.pipeline_runs(run_id),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(dataset_key,cycle_number,issue_key)
);
CREATE INDEX IF NOT EXISTS idx_dq_issue_batch ON demo_control.dq_issue(dataset_key,cycle_number,batch,status);

CREATE OR REPLACE FUNCTION demo_control.guard_dq_issue() RETURNS trigger AS $fn$
BEGIN
  IF TG_OP='DELETE' THEN
    RAISE EXCEPTION 'dq_issue rows are an audit record and cannot be deleted' USING ERRCODE='check_violation';
  END IF;
  IF (OLD.issue_key,OLD.dataset_key,OLD.cycle_number,OLD.batch,OLD.first_run_id,OLD.rule_id,OLD.severity,
      OLD.table_name,OLD.source_file,OLD.source_file_sha256,OLD.source_zip_sha256,OLD.source_row_no,
      OLD.pk_json,OLD.column_name,OLD.invalid_value,OLD.parent_table,OLD.parent_column,
      OLD.row_snapshot,OLD.context,OLD.created_at)
     IS DISTINCT FROM
     (NEW.issue_key,NEW.dataset_key,NEW.cycle_number,NEW.batch,NEW.first_run_id,NEW.rule_id,NEW.severity,
      NEW.table_name,NEW.source_file,NEW.source_file_sha256,NEW.source_zip_sha256,NEW.source_row_no,
      NEW.pk_json,NEW.column_name,NEW.invalid_value,NEW.parent_table,NEW.parent_column,
      NEW.row_snapshot,NEW.context,NEW.created_at) THEN
    RAISE EXCEPTION 'Original dq_issue evidence is immutable' USING ERRCODE='check_violation';
  END IF;
  RETURN NEW;
END $fn$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_guard_dq_issue ON demo_control.dq_issue;
CREATE TRIGGER trg_guard_dq_issue BEFORE UPDATE OR DELETE ON demo_control.dq_issue
  FOR EACH ROW EXECUTE FUNCTION demo_control.guard_dq_issue();

-- 5. Append-only correction ledger (versioned; never updated or deleted).
CREATE TABLE IF NOT EXISTS demo_control.dq_correction (
 correction_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 issue_id UUID NOT NULL REFERENCES demo_control.dq_issue(issue_id),
 version INTEGER NOT NULL CHECK(version>=1),
 original_value TEXT,
 corrected_value TEXT NOT NULL CHECK(length(corrected_value)>0),
 actor TEXT NOT NULL CHECK(length(btrim(actor)) BETWEEN 1 AND 120),
 reason TEXT NOT NULL CHECK(length(btrim(reason)) BETWEEN 10 AND 2000),
 evidence_ref TEXT NOT NULL CHECK(length(btrim(evidence_ref)) BETWEEN 3 AND 1000),
 supersedes_correction_id UUID REFERENCES demo_control.dq_correction(correction_id),
 idempotency_key TEXT NOT NULL UNIQUE CHECK(length(idempotency_key) BETWEEN 8 AND 100),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(issue_id,version)
);
CREATE OR REPLACE FUNCTION demo_control.guard_append_only() RETURNS trigger AS $fn$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE='check_violation';
END $fn$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_dq_correction_append_only ON demo_control.dq_correction;
CREATE TRIGGER trg_dq_correction_append_only BEFORE UPDATE OR DELETE ON demo_control.dq_correction
  FOR EACH ROW EXECUTE FUNCTION demo_control.guard_append_only();

-- Effective (latest) correction per issue and a single definition of the correction-set identity.
CREATE OR REPLACE VIEW demo_control.dq_effective_correction AS
SELECT DISTINCT ON (c.issue_id)
       c.correction_id,c.issue_id,c.version,c.original_value,c.corrected_value,c.actor,c.reason,
       c.evidence_ref,c.created_at,
       i.dataset_key,i.cycle_number,i.batch,i.table_name,i.pk_json,i.column_name,i.source_zip_sha256
  FROM demo_control.dq_correction c JOIN demo_control.dq_issue i ON i.issue_id=c.issue_id
 ORDER BY c.issue_id,c.version DESC;

CREATE OR REPLACE FUNCTION demo_control.dq_correction_set_id(p_dataset TEXT,p_cycle INTEGER,p_batch TEXT,p_zip TEXT)
RETURNS TEXT AS $fn$
  SELECT md5(string_agg(e.issue_id::text||':'||e.version::text||':'||e.corrected_value, ',' ORDER BY e.issue_id))
    FROM demo_control.dq_effective_correction e
   WHERE e.dataset_key=p_dataset AND e.cycle_number=p_cycle AND e.batch=p_batch
     AND e.source_zip_sha256 IS NOT DISTINCT FROM p_zip;
$fn$ LANGUAGE sql STABLE;

-- 6. Revalidation of a correction set with the original rule catalog.
CREATE TABLE IF NOT EXISTS demo_control.dq_revalidation (
 reval_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 dataset_key TEXT NOT NULL DEFAULT 'classroom',
 cycle_number INTEGER NOT NULL CHECK(cycle_number>=1),
 batch TEXT NOT NULL,
 blocked_run_id UUID REFERENCES demo_control.pipeline_runs(run_id),
 correction_set_id TEXT,
 source_zip_sha256 TEXT CHECK(source_zip_sha256 IS NULL OR source_zip_sha256 ~ '^[0-9a-f]{64}$'),
 rules_executed INTEGER NOT NULL,
 failed_rules INTEGER NOT NULL,
 failed_rows BIGINT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('PASS','FAIL')),
 results JSONB NOT NULL DEFAULT '{}'::jsonb,
 actor TEXT,
 executed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dq_revalidation_batch ON demo_control.dq_revalidation(dataset_key,cycle_number,batch,executed_at DESC);

-- 7. Published snapshot registry: the only thing a dashboard should treat as "published".
CREATE TABLE IF NOT EXISTS demo_control.published_snapshot (
 snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 dataset_key TEXT NOT NULL DEFAULT 'classroom',
 cycle_number INTEGER NOT NULL CHECK(cycle_number>=1),
 batch TEXT NOT NULL,
 run_id UUID NOT NULL UNIQUE REFERENCES demo_control.pipeline_runs(run_id),
 source_version TEXT,
 source_zip_sha256 TEXT CHECK(source_zip_sha256 IS NULL OR source_zip_sha256 ~ '^[0-9a-f]{64}$'),
 correction_set_id TEXT,
 artifact_uri TEXT,
 published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 is_current BOOLEAN NOT NULL DEFAULT TRUE,
 UNIQUE(dataset_key,cycle_number,batch)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_published_snapshot_current
  ON demo_control.published_snapshot(dataset_key,cycle_number) WHERE is_current;

COMMIT;

-- ---------------- demo_ml ----------------
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
