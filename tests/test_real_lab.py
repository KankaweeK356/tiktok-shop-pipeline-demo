"""Safe contract checks for real step execution and 10% SKU screening.

No real Neon writes: active demo cycle and 900 orders remain untouched.
"""
import ast
from pathlib import Path

from pipeline.schema import ROOT


def test_real_one_step_python_contract():
    source=(ROOT/"pipeline"/"ci_lab_stage.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert "run_batch(workspace,batch,stop_after=stage)" in source
    assert 'if phase != required:' in source
    assert 'begin_run(db_url' in source
    assert 'complete_run(db_url' in source
    assert "last_completed" in source
    assert "last_step_result.json" in source
    assert 'mode":"REAL_GITHUB_ACTIONS_STAGE"' in source


def test_workflow_restores_previous_workspace_and_preserves_results():
    s=(ROOT/".github"/"workflows"/"classroom-real-step.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in s
    assert "actions/download-artifact@v4" in s
    assert "actions/upload-artifact@v4" in s
    assert "github-token:" in s
    assert "classroom-lab-workspace" in s
    assert "classroom-lab-result" in s
    assert "NEON_DEMO_DATABASE_URL:" in s
    assert "cancel-in-progress: false" in s
    assert "RESET-DEMO-DATA" not in s


def test_frontend_labels_real_execution_distinct_from_readonly_replay():
    s=(ROOT/"dashboard"/"app.js").read_text(encoding="utf-8")
    assert "REAL_GITHUB_ACTIONS_STAGE" in s
    assert "READ_ONLY_EVIDENCE_REPLAY" in s
    assert '"/api/lab-dispatch"' in s
    assert '"/api/lab-real-result?run_id="' in s
    assert "Execute Real ETL Step" in s
    assert "pre_group_shortfall_thb" in s
    assert "gross*benchmarkPct/100" in s


def test_dispatch_requires_server_side_token_and_admin_authorization():
    s=(ROOT/"api"/"lab-dispatch.js").read_text(encoding="utf-8")
    assert "CLASSROOM_GITHUB_TOKEN" in s
    assert "CLASSROOM_LAB_ADMIN_KEY" in s
    assert "timingSafeEqual" in s
    assert "workflow_dispatch" in s
    assert "REF=" in s
    assert 'rows[0]?.phase!==expected' in s
    assert 'return json(res,409' in s
    assert "RESET-DEMO-DATA" not in s


def test_worker_output_is_from_real_rows_not_example_constants():
    s=(ROOT/"pipeline"/"ci_lab_stage.py").read_text(encoding="utf-8")
    assert '"Fact_Orders" LIMIT 5' in s
    assert '"Fact_Sales_Order_Item" LIMIT 5' in s
    assert "ParquetFile" in s
    assert 'pd.read_csv' not in s or "head" in s
