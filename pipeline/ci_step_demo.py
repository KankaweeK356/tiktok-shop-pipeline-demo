from __future__ import annotations

from pipeline.schema import ROOT
import nbformat


def main() -> None:
    path = ROOT / "notebooks" / "TikTok_Shop_Step_by_Step_Demo.ipynb"
    notebook = nbformat.read(path, as_version=4)
    nbformat.validate(notebook)
    code = "\n".join(cell.source for cell in notebook.cells if cell.cell_type == "code")
    required = (
        "เริ่มรอบใหม่และรัน Run 1",
        "เติมข้อมูลเดือนถัดไป",
        "เคลียร์ผลทดลองใน Colab",
        "ทดสอบ Error แยก",
        "run_batch(WORKSPACE,batch,source_root=SOURCE)",
        "BATCHES[index]",
        "os.environ.pop(\"NEON_DEMO_DATABASE_URL\",None)",
    )
    missing = [item for item in required if item not in code]
    if missing:
        raise AssertionError("Interactive Colab journey is missing: " + ", ".join(missing))
    for index, cell in enumerate(notebook.cells):
        if cell.cell_type == "code":
            compile(cell.source, f"{path}:cell{index}", "exec")
    if "for batch in BATCHES:" in code:
        raise AssertionError("Interactive Pipeline Notebook must not auto-run every month")
    print("COLAB NOTEBOOK: setup and one-month-at-a-time controls are present")


if __name__ == "__main__":
    main()
