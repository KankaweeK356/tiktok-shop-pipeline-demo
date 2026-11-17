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
