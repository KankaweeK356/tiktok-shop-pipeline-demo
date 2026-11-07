"""Run every Step-by-Step Colab cell sequentially using real SQLite, PyArrow, DuckDB.

Every stage is asserted before the next stage begins, proving that the notebook
actually demonstrates Source -> ER1 -> Lake -> ER2 -> Validation, then incremental,
replay, and error recovery rather than executing one hidden batch.
"""
from __future__ import annotations

import os
from pathlib import Path
os.environ.setdefault("MPLBACKEND", "Agg")

import nbformat
from .schema import ROOT
from .orchestrator import reset


def main():
    notebook = nbformat.read(ROOT / "notebooks" / "TikTok_Shop_Step_by_Step_Demo.ipynb", as_version=4)
    nbformat.validate(notebook)
    reset(ROOT / "output" / "main")
    ctx = {"__name__": "__main__"}
    code_cells = [cell for cell in notebook.cells if cell.cell_type == "code"]
    expected = 17
    assert len(code_cells) == expected, (len(code_cells), expected)
    for i, cell in enumerate(code_cells):
        print(f"START STAGED CELL {i:02d}: {cell.source.splitlines()[0]}", flush=True)
        exec(compile(cell.source, f"staged-cell-{i}", "exec"), ctx)
        workspace = ROOT / "output" / "main"
        if i == 2:
            assert (workspace / "er1.sqlite").is_file()
            assert not (workspace / "er2.duckdb").is_file()
        elif i == 3:
            assert (workspace / "lake" / "raw" / "initial" / "Fact_Orders.parquet").is_file()
            assert not (workspace / "er2.duckdb").is_file()
        elif i == 4:
            assert (workspace / "lake" / "standardized" / "initial" / "Fact_Sales_Order_Item.parquet").is_file()
        elif i == 5:
            assert (workspace / "er2.duckdb").is_file()
        elif i == 6:
            assert ctx["initial_result"]["status"] == "SUCCESS"
        elif i == 7:
            assert len(ctx["new_orders"]) > 0 and len(ctx["changed_orders"]) > 0
        elif i == 8:
            assert "ingest" in ctx["stage"]["completed"]
        elif i == 9:
            assert (workspace / "lake" / "raw" / "incremental" / "Fact_Orders.parquet").is_file()
        elif i == 10:
            assert len(ctx["std_delta"]) > 0
        elif i == 11:
            assert ctx["after_load"]["orders"] > ctx["INITIAL_SIGNATURE"]["orders"]
        elif i == 12:
            assert ctx["final_check"]["failed"] == 0
        elif i == 13:
            assert ctx["after_replay"] == ctx["before_replay"]
        elif i == 14:
            assert ctx["chosen"]["passed"].all()
        elif i == 15:
            assert len(ctx["six"]) == 6 and ctx["six"]["passed"].all()
            assert len(ctx["perf"]) == 2
            assert Path(ctx["evidence"]["zip_path"]).is_file()
        print(f"PASS STAGED CELL {i:02d}", flush=True)
    print("STEP-BY-STEP SOURCE / ER1 / LAKE / ER2 / INCREMENTAL / REPLAY / ERROR: ALL PASSED", flush=True)


if __name__ == "__main__":
    main()
