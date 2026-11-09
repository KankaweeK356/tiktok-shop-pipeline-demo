"""Lightweight evidence contract tests, no live Neon modifications."""
from pathlib import Path
import ast

from pipeline.schema import ROOT, parse_dbml


def test_classroom_evidence_export_includes_all_required_layers():
    source = (ROOT / "pipeline" / "classroom_evidence.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert any(isinstance(n, ast.FunctionDef) and n.name == "export_classroom_evidence"
               for n in ast.walk(tree))
    for name in ("source", "landing", "raw", "standardized",
                 "warehouse", "governance", "control"):
        assert f'"{name}"' in source


def test_warehouse_and_source_schema_counts_unchanged():
    source, _ = parse_dbml(ROOT / "schemas" / "ER1_V3.dbml")
    warehouse, _ = parse_dbml(ROOT / "schemas" / "ER2_V5.dbml")
    assert len(source) == 25
    assert len(warehouse) == 12
    assert sum(t.name.startswith("View_") for t in warehouse) == 1


def test_export_cannot_claim_neon_is_connected():
    source = (ROOT / "pipeline" / "classroom_evidence.py").read_text(encoding="utf-8")
    assert '"neon_connected": False' in source
    assert '"source_engine": "SQLITE_NOT_NEON"' in source
    assert '"classification": "SYNTHETIC_EDUCATIONAL_NOT_TIKTOK"' in source
