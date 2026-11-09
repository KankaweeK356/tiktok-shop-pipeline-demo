"""Neon PostgreSQL adapter for the classroom demo.

The existing SQLite ingester performs deterministic synthetic business
calculations. When NEON_DEMO_DATABASE_URL is configured, we transactionally
publish all 25 computed source tables into Neon and extract Raw from Neon.
Never embed connection strings in artifacts or logs.

This is an optional mode. Offline Colab / CI must remain fully functional.
"""
from __future__ import annotations

import json
import hashlib
import shutil
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from .schema import ROOT, parse_dbml


def _ordered_source_tables():
    tables, refs = parse_dbml(ROOT / "schemas" / "ER1_V3.dbml")
    dependencies = {t.name: set() for t in tables}
    for child, _, parent, _ in refs:
        dependencies[child].add(parent)
    remaining = {t.name: t for t in tables}
    ordered = []
    while remaining:
        available = sorted(
            name for name in remaining
            if dependencies[name].isdisjoint(remaining)
        )
        if not available:
            raise ValueError("Cycle in source database foreign keys")
        for name in available:
            ordered.append(remaining.pop(name))
    return ordered


def _quoted(name: str) -> str:
    if not name.replace("_", "").isalnum() or name[0].isdigit():
        raise ValueError("Invalid database identifier")
    return '"' + name + '"'


def _convert_insert(value, typ: str):
    if value is None:
        return None
    if typ == "boolean":
        return bool(value)
    if typ == "date" and isinstance(value, str):
        return date.fromisoformat(value[:10])
    if typ == "datetime" and isinstance(value, str):
        return datetime.fromisoformat(value)
    if typ == "decimal":
        return Decimal(str(value))
    return value


def _convert_extract(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bool):
        return int(value)
    return value


def sync_sqlite_to_neon(source_sqlite: Path, database_url: str) -> dict:
    """Atomic upsert in FK-safe order. Idempotent for the same SQLite snapshot.

    Restrict database_url to the demo-pipeline branch, never analytics/main.
    This function does not delete rows; reset is a separate confirmed action.
    """
    import psycopg
    source_sqlite = Path(source_sqlite)
    if not source_sqlite.is_file():
        raise FileNotFoundError(source_sqlite)
    result = {}
    source = sqlite3.connect(f"file:{source_sqlite.resolve()}?mode=ro", uri=True)
    try:
        with psycopg.connect(database_url) as dest:
            with dest.cursor() as cursor:
                for table in _ordered_source_tables():
                    name = table.name
                    cols = [column.name for column in table.columns]
                    src = source.execute(
                        "SELECT " + ",".join(_quoted(c) for c in cols) +
                        " FROM " + _quoted(name)
                    )
                    rows = src.fetchall()
                    placeholders = ",".join(["%s"] * len(cols))
                    conflict = ",".join(_quoted(c) for c in table.pk)
                    updates = [c for c in cols if c not in table.pk]
                    action = ("DO UPDATE SET " + ",".join(
                        _quoted(c) + "=EXCLUDED." + _quoted(c) for c in updates
                    )) if updates else "DO NOTHING"
                    statement = (
                        'INSERT INTO demo_er1.' + _quoted(name) + ' (' +
                        ",".join(_quoted(c) for c in cols) + ') VALUES (' +
                        placeholders + ') ON CONFLICT (' + conflict + ') ' + action
                    )
                    types = [c.typ for c in table.columns]
                    cursor.executemany(
                        statement,
                        [tuple(_convert_insert(v, typ) for v, typ in zip(row, types))
                         for row in rows]
                    )
                    cursor.execute('SELECT COUNT(*) FROM demo_er1.' + _quoted(name))
                    new_count = cursor.fetchone()[0]
                    if new_count != len(rows):
                        raise AssertionError(
                            f"Neon table {name} has {new_count} records; expected {len(rows)}"
                        )
                    result[name] = {"rows": new_count}
            # Commit only after every table passed row-count reconciliation.
    finally:
        source.close()
    return {"source_engine": "NEON_POSTGRESQL", "tables": len(result),
            "table_counts": result}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def extract_neon(source_dir: Path, database_url: str, lake_dir: Path, batch: str):
    """Landing CSV + true 25-table PostgreSQL Raw Parquet snapshot."""
    import psycopg
    landing = Path(lake_dir) / "landing" / batch
    raw = Path(lake_dir) / "raw" / batch
    landing.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    manifest = {"batch_id": batch, "source_engine": "NEON_POSTGRESQL",
                "landing": {}, "raw": {},
                "mode": "Neon source table snapshots; delta by batch change keys"}
    for path in sorted(Path(source_dir).glob("*.csv")):
        copied = landing / path.name
        shutil.copy2(path, copied)
        manifest["landing"][path.name] = {
            "sha256": _sha256(copied), "bytes": copied.stat().st_size
        }
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cursor:
            for table in _ordered_source_tables():
                cursor.execute("SELECT * FROM demo_er1." + _quoted(table.name))
                cols = [item.name for item in cursor.description]
                data = [tuple(_convert_extract(v) for v in row)
                        for row in cursor.fetchall()]
                frame = pd.DataFrame(data, columns=cols)
                output = raw / (table.name + ".parquet")
                frame.to_parquet(output, index=False, engine="pyarrow")
                manifest["raw"][table.name] = {
                    "records": len(frame), "sha256": _sha256(output),
                    "relative_path": str(output.relative_to(lake_dir))
                }
    control = Path(lake_dir) / "control"
    governance = Path(lake_dir) / "governance"
    control.mkdir(parents=True, exist_ok=True)
    governance.mkdir(parents=True, exist_ok=True)
    tables = _ordered_source_tables()
    (governance / f"schema_receipt_{batch}.json").write_text(json.dumps({
        "batch": batch, "source_engine": "NEON_POSTGRESQL",
        "er1_table_count": len(tables),
        "table_columns": {t.name: [c.name for c in t.columns] for t in tables},
        "source_file_checksums": manifest["landing"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (control / f"manifest_{batch}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"parquet_tables": len(tables),
            "source_files": len(manifest["landing"]),
            "source_engine": "NEON_POSTGRESQL",
            "raw_records": sum(t["records"] for t in manifest["raw"].values())}
