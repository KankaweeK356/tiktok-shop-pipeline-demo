"""Unit tests: publishing real one-step evidence never includes cloud credentials."""
import json
from pathlib import Path

import pytest

from pipeline import publish_lab_result as publisher


def test_publish_real_worker_receipt_is_small_and_source_backed(tmp_path,monkeypatch):
    monkeypatch.setattr(publisher,"ROOT",tmp_path)
    monkeypatch.setenv("GITHUB_RUN_ID","42577788046")
    source=tmp_path/"output"/"classroom_lab"
    source.mkdir(parents=True)
    (source/"last_step_result.json").write_text(json.dumps({
        "execution":"GITHUB_ACTIONS_REAL_PIPELINE_STAGE",
        "batch":"initial","stage":"ingest","cycle":1,"run_id":"uuid-xyz",
        "connection_string":"SHOULD_NOT_LEAK",
        "evidence":{
            "classification":"SYNTHETIC_EDUCATIONAL_NOT_TIKTOK",
            "mode":"REAL_GITHUB_ACTIONS_STAGE",
            "is_new_etl_run":True,"stage":"ingest","batch":"initial",
            "executed_at":"2026-11-09T07:08:24+00:00","success":True,
            "input":{"label":"source"},
            "output":{"records":800,"preview":[{"Order_ID":"DEMO001"}]},
            "metrics":[{"label":"Orders","value":800}],
            "checks":[{"label":"Rows reconciled","pass":True}],
            "provenance":"NEW_WORKER_OUTPUT_NOT_HISTORICAL_REPLAY",
            "secret":"MUST_NOT_BE_PUBLISHED"
        }
    }),encoding="utf-8")
    publisher.main()
    path=tmp_path/"dashboard"/"data"/"lab_steps"/"initial_ingest.json"
    raw=path.read_text(encoding="utf-8")
    assert "MUST_NOT_BE_PUBLISHED" not in raw
    assert "SHOULD_NOT_LEAK" not in raw
    data=json.loads(raw)
    assert data["evidence"]["output"]["records"]==800
    assert data["git_run_id"]=="42577788046"
    manifest=json.loads((tmp_path/"dashboard"/"data"/"lab_manifest.json").read_text())
    assert manifest["runs"][0]["stage"]=="ingest"
    assert manifest["source"]=="REAL_GITHUB_ACTIONS_SEPARATE_STAGES"


def test_publisher_rejects_non_worker_evidence(tmp_path,monkeypatch):
    monkeypatch.setattr(publisher,"ROOT",tmp_path)
    directory=tmp_path/"output"/"classroom_lab"
    directory.mkdir(parents=True)
    (directory/"last_step_result.json").write_text(json.dumps({
        "execution":"ARCHIVED_SNAPSHOT",
        "batch":"initial","stage":"ingest","evidence":{"mode":"READ_ONLY_EVIDENCE_REPLAY"}
    }))
    with pytest.raises(RuntimeError):
        publisher.main()
