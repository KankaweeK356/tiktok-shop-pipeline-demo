"""Execute every user-facing Google Colab code cell using the real CI engines.

This catches failures in the interactive presentation itself (matplotlib, column
selection, reporting) that calling the pipeline functions alone can miss.
Drive is intentionally optional: DRIVE_ACTION defaults to none in the notebook.
"""
from __future__ import annotations

import os
from pathlib import Path

# Headless Matplotlib is required for GitHub-hosted test runners.
os.environ.setdefault("MPLBACKEND", "Agg")

import nbformat
from pipeline.schema import ROOT


def main():
    notebook_path = ROOT / "notebooks" / "TikTok_Shop_Demo.ipynb"
    notebook = nbformat.read(notebook_path, as_version=4)
    nbformat.validate(notebook)
    namespace = {"__name__": "__main__"}

    # All sections start with the normal default form selections. No Google
    # Drive permissions, credentials, or writes are necessary for this test.
    required_cells = [2, 4, 6, 8, 10, 12, 14, 16, 17, 20, 22]
    for cell_number in required_cells:
        cell = notebook.cells[cell_number]
        if cell.cell_type != "code":
            raise AssertionError(f"Expected code cell at position {cell_number}")
        source = cell.source
        print(f"BEGIN COLAB CELL {cell_number}: {source.splitlines()[0]}", flush=True)
        try:
            exec(compile(source, f"notebook-cell-{cell_number}", "exec"), namespace)
        except Exception:
            print(f"FAILED COLAB CELL {cell_number}", flush=True)
            raise
        if cell_number == 6:
            assert namespace["run1"]["status"] == "SUCCESS"
        elif cell_number == 8:
            assert namespace["run2"]["status"] == "SUCCESS"
        elif cell_number == 12:
            assert namespace["error_results"]["passed"].all()
        elif cell_number == 14:
            assert len(namespace["six"]) == 6 and namespace["six"]["passed"].all()
        elif cell_number == 16:
            assert len(namespace["perf"]) == 3
        elif cell_number == 17:
            assert not namespace["monthly"].empty and not namespace["groups"].empty
        elif cell_number == 20:
            assert Path(namespace["published"]["zip_path"]).is_file()
        print(f"PASS COLAB CELL {cell_number}", flush=True)
    print("COLAB NOTEBOOK USER JOURNEY: ALL CELLS PASSED", flush=True)


if __name__ == "__main__":
    main()
