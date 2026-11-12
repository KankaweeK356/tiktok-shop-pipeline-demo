"""Export the completed DuckDB warehouse as one CSV per table."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import duckdb

from .ci_lab_stage import STATE_PATH


def main() -> None:
    workspace = STATE_PATH.parent
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    batch = state["batch"]
    checkpoint = workspace / "lake" / "control" / f"checkpoint_{batch}.json"
    completed = json.loads(checkpoint.read_text(encoding="utf-8"))["completed"]
    if "load" not in completed:
        raise RuntimeError("Warehouse export requires a completed Load stage")
    output = workspace / "warehouse_export"
    output.mkdir(exist_ok=True)
    manifest = {"batch": batch, "cycle": state["cycle"],
                "run_id": state["run_id"], "tables": []}
    with duckdb.connect(str(workspace / "er2.duckdb"), read_only=True) as db:
        tables = [row[0] for row in db.execute("SHOW TABLES").fetchall()]
        for name in tables:
            if not name.replace("_", "").isalnum():
                raise RuntimeError("Unsafe warehouse table name")
            target = output / f"{name}.csv"
            escaped = str(target).replace("'", "''")
            db.execute(f'COPY (SELECT * FROM "{name}") TO \'{escaped}\' (HEADER, DELIMITER \',\')')
            count = db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            manifest["tables"].append({"name": name, "rows": count})
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    archive = workspace / "warehouse_csv.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(output.iterdir()):
            zipped.write(path, path.name)
    print(json.dumps({"warehouse_tables": len(tables), "archive": archive.name}))


if __name__ == "__main__":
    main()
