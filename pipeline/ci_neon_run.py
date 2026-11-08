"""Controlled one-run end-to-end Neon-source verification.

Offline synthetic loader computes business fields in local SQLite, then publishes
25 tables transactionally to real Neon. Raw Parquet is extracted FROM Neon;
Standardized and DuckDB remain the existing validated pipeline.

This runner refuses a non-empty Neon demo branch to prevent overwriting another
session. It does not provide multi-user web Run/Reset controls yet.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

import psycopg

from .schema import ROOT
from .orchestrator import run_batch, reset
from .demo_tests import signature


def _assert_empty(database_url: str):
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT table_name FROM information_schema.tables
                 WHERE table_schema='demo_er1' AND table_type='BASE TABLE'
            """)
            names = [r[0] for r in cursor.fetchall()]
            if len(names) != 25:
                raise RuntimeError("Neon ER1 schema must contain exactly 25 tables")
            for name in names:
                cursor.execute('SELECT 1 FROM demo_er1."' + name + '" LIMIT 1')
                if cursor.fetchone():
                    raise RuntimeError(
                        "Existing Neon demo data found. Reset must be explicitly "
                        "confirmed before starting another cycle: " + name
                    )


def main():
    db_url = os.getenv("NEON_DEMO_DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            "Configure the GitHub Actions secret NEON_DEMO_DATABASE_URL for "
            "the demo-pipeline branch; never put the URL in source code"
        )
    _assert_empty(db_url)
    ws = ROOT / "output" / "neon_demo"
    reset(ws)
    run1 = run_batch(ws, "initial")
    before = signature(ws)
    run2 = run_batch(ws, "incremental")
    after = signature(ws)
    replay = run_batch(ws, "incremental")
    stable = signature(ws) == after
    if (run1["status"] != "SUCCESS" or run2["status"] != "SUCCESS"
            or replay["status"] != "SUCCESS" or
            run1["functional_fails"] or run2["functional_fails"] or
            not stable or after["orders"] <= before["orders"]):
        raise AssertionError("Cloud source pipeline validation failed")
    payload = {
        "classification": "SYNTHETIC_EDUCATIONAL_NOT_TIKTOK",
        "source": "NEON_POSTGRESQL_DEMO_BRANCH",
        "raw_extraction": "FROM_NEON",
        "run1_status": run1["status"],
        "run2_status": run2["status"],
        "replay_idempotent": stable,
        "paid_items_run1": before["orders"],
        "paid_items_run2": after["orders"],
        "net_revenue_run1": before["sales"],
        "net_revenue_run2": after["sales"],
        "stage_checkpoints": {
            name: json.loads((ws/"lake"/"control"/f"checkpoint_{name}.json").read_text())
            for name in ["initial", "incremental"]
        },
    }
    output = ws / "reports" / "neon_pipeline_verification.json"
    output.parent.mkdir(exist_ok=True, parents=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    print(json.dumps({k:v for k,v in payload.items() if k!="stage_checkpoints"},
                     indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
