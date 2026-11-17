"""Revalidation of human corrections with the *same* generic rules as the Stage 1 gate.

The corrections are an effective overlay over the preserved original CSV rows
(`dq.apply_corrections`). Nothing is written to ER1, Neon business tables or the
Source ZIP here; this module only produces a DQ report that the caller persists.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from . import dq
from .er1 import SOURCE_ORDER, load_csv


def stage_rows(source_dir: Path) -> dict[str, list[dict]]:
    return {t: load_csv(Path(source_dir) / f"{t}.csv", t) for t in SOURCE_ORDER
            if (Path(source_dir) / f"{t}.csv").exists()}


def revalidate(workspace: Path, source_dir: Path, batch: str, identity: dict, context: dict) -> dict:
    """Run the Stage 1 rule catalog on raw rows + approved corrections."""
    staged = stage_rows(source_dir)
    db_path = Path(workspace) / "er1.sqlite"
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) if db_path.is_file() else None
    try:
        existing = dq.sqlite_universe(conn) if conn else None
        return dq.evaluate(
            staged, batch=batch, stage="ingest", existing=existing, identity=identity,
            corrections={"correction_set_id": context.get("correction_set_id"),
                         "corrections": context.get("corrections", [])},
            evaluation_kind="REVALIDATION")
    finally:
        if conn:
            conn.close()
