"""Guardrails around classroom Neon control, not a destructive live DB test."""
import ast
from pathlib import Path
from pipeline.schema import ROOT


def test_control_transitions_and_actual_evidence():
    source=(ROOT/"pipeline"/"neon_control.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert '"RUN1": "EMPTY"' in source
    assert '"RUN2": "RUN1_READY"' in source
    assert '"REPLAY": "RUN2_READY"' in source
    assert "stage_history.jsonl" in source
    assert "FROM demo_control.dataset_state" in source


def test_reset_is_manual_and_cannot_cascade_or_drop():
    source=(ROOT/"pipeline"/"neon_reset.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert 'CONFIRM_PHRASE = "RESET-DEMO-DATA"' in source
    assert 'for table in reversed(tables):' in source
    assert 'cur.execute("DELETE FROM demo_er1."+_quoted(table.name))' in source
    assert "TRUNCATE TABLE" not in source
    assert "DROP TABLE" not in source
    assert "demo_control.reset_audit" in source
    assert "Cannot reset while a pipeline run is active" in source


def test_archiving_cannot_rewrite_existing_neon_source():
    source=(ROOT/"pipeline"/"archive_recovery.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert 'os.environ.pop("NEON_DEMO_DATABASE_URL")' in source
    assert "NEW_NEON_SNAPSHOT_AND_OFFLINE_WAREHOUSE_RECONSTRUCTION" in source
    assert 'original_run1_parquet_available": False' in source
    assert "pipeline_artifacts" in source


def test_web_status_binds_live_artifact_and_count_queries_in_correct_order():
    source=(ROOT/"api"/"neon-status.js").read_text(encoding="utf-8")
    assert "const [state,runs,files,counts]=await Promise.all([" in source
    assert "archived_files:files" in source
    assert "counts:counts[0]" in source
    assert "r.cycle_number=d.cycle_number" in source
