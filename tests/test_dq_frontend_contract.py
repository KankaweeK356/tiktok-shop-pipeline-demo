"""Frontend/API contract checks that run without a browser or a database."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed (NOT_TESTED)")
def test_node_unit_tests_for_pipeline_state_and_review_fix_api():
    done = subprocess.run(["node", "--test", *map(str, sorted((ROOT / "tests" / "js").glob("*.test.mjs")))],
                          capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert done.returncode == 0, done.stdout[-1500:] + done.stderr[-500:]


def test_pipeline_page_loads_state_helper_before_app_and_function_bundle_has_the_lock():
    html = (ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")
    assert html.index("pipeline-state.js") < html.index("app.js")
    vercel = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    assert "source_lock_classroom_v2.json" in vercel["functions"]["api/lab-worker.py"]["includeFiles"]


def test_ui_has_no_fabricated_error_state_and_reads_issues_from_backend():
    app = (ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
    for fake in ("marchBlocked", "marchOverride", "DIM_SKU_OPTIONS", "ORD-202603", "SKU_ERR_UNKNOWN_DEMO",
                 "ใบกำกับคำสั่งซื้อต้นฉบับ #ORD", "PASS (6/6 กฎ)", "bb9c847e"):
        assert fake not in app
    assert 'dqApi("state")' in app and 'dqApi("candidates"' in app and 'dqApi("correct"' in app
    assert "state.dq.blocked" in app and "refreshDqState" in app
    worker = (ROOT / "api" / "lab-worker.py").read_text(encoding="utf-8")
    assert "claim.get(\"override\")" not in worker and "override" not in worker.lower()
