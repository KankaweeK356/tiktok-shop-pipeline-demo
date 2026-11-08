"""Neon schema deployment contract (offline; never touches live DB)."""
from pathlib import Path
import re

from pipeline.schema import ROOT, parse_dbml


def test_neon_ddl_matches_er1_contract():
    sql = (ROOT / "sql" / "neon_er1_demo_bootstrap.sql").read_text(encoding="utf-8")
    tables, references = parse_dbml(ROOT / "schemas" / "ER1_V3.dbml")
    assert len(tables) == 25
    assert len(references) == 26
    business = re.findall(
        r'CREATE TABLE IF NOT EXISTS demo_er1\."([A-Za-z_]\w*)"', sql
    )
    assert sorted(business) == sorted(t.name for t in tables)
    constraints = re.findall(r'ADD CONSTRAINT "fk_\w+" FOREIGN KEY', sql)
    assert len(constraints) == 26
    control = re.findall(
        r'CREATE TABLE IF NOT EXISTS demo_control\.(\w+)', sql
    )
    assert set(control) == {
        "dataset_state", "pipeline_runs", "stage_runs",
        "reset_audit", "pipeline_artifacts", "stage_events", "upload_sessions",
    }
    for table in tables:
        names = re.findall(
            r'(?m)^  "([A-Za-z_]\w*)" (?:TEXT|NUMERIC\(20,4\)|BIGINT|INTEGER|BOOLEAN|DATE|TIMESTAMP)',
            sql.split(f'CREATE TABLE IF NOT EXISTS demo_er1."{table.name}" (')[1].split('\n);', 1)[0],
        )
        assert names == [c.name for c in table.columns], table.name


def test_bootstrap_never_clears_business_data():
    sql = (ROOT / "sql" / "neon_er1_demo_bootstrap.sql").read_text(encoding="utf-8")
    assert not re.search(r'\b(TRUNCATE|DELETE FROM|DROP TABLE|DROP SCHEMA)\b', sql, re.IGNORECASE)
    assert "ON CONFLICT (dataset_key) DO NOTHING" in sql


def test_demo_control_is_separate_from_business_er1():
    sql = (ROOT / "sql" / "neon_er1_demo_bootstrap.sql").read_text(encoding="utf-8")
    assert "UNIQUE(dataset_key,cycle_number,run_type,request_key)" in sql
    assert "'EMPTY','RUN1_READY','RUN2_READY'" in sql
    assert "demo_control.reset_audit" in sql
    assert "demo_control.stage_events" in sql
    assert "demo_control.pipeline_artifacts" in sql
