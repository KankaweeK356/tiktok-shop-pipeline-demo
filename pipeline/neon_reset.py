"""Explicit and transactional reset of ONLY Neon demo source records.

This command is never part of normal CI and NEVER automatically executed.
It preserves 25 ER1 tables, 6+ demo_control metadata tables and historical
run evidence. Files under previous immutable archive prefixes are retained
for audit until a separate explicit retention cleanup; not active cycle data.

GitHub workflow requires two-factor-like operator intent: exact phrase and
expected cycle. It blocks reset when any run or upload session is active.
"""
from __future__ import annotations

import argparse
import os

import psycopg

from .neon_source import _ordered_source_tables, _quoted

CONFIRM_PHRASE = "RESET-DEMO-DATA"


def reset_source(database_url: str, *, confirmation: str,
                 expected_cycle: int, actor: str, reason: str) -> dict:
    if confirmation != CONFIRM_PHRASE:
        raise ValueError("Reset requires exact typed phrase RESET-DEMO-DATA")
    if expected_cycle < 1 or not actor.strip() or not reason.strip():
        raise ValueError("Expected cycle, actor and reason are mandatory")
    tables=_ordered_source_tables()
    if len(tables)!=25:
        raise RuntimeError("Unexpected ER1 contract; refusing reset")
    with psycopg.connect(database_url) as db:
        with db.cursor() as cur:
            cur.execute("SELECT phase,cycle_number FROM demo_control.dataset_state "
                        "WHERE dataset_key='classroom' FOR UPDATE")
            current=cur.fetchone()
            if not current or current[1] != expected_cycle:
                raise RuntimeError("Current data cycle changed; no reset performed")
            previous_phase,current_cycle=current
            cur.execute("""
                SELECT COUNT(*) FROM demo_control.pipeline_runs
                 WHERE dataset_key='classroom' AND cycle_number=%s
                   AND status IN ('RUNNING','QUEUED')
            """,(current_cycle,))
            if cur.fetchone()[0]:
                raise RuntimeError("Cannot reset while a pipeline run is active")
            cur.execute("""
                SELECT COUNT(*) FROM demo_control.upload_sessions
                 WHERE revoked=FALSE AND expires_at>now()
            """)
            if cur.fetchone()[0]:
                raise RuntimeError("Cannot reset during an active storage upload")
            names=", ".join("demo_er1."+_quoted(t.name) for t in tables)
            # All 25 tables are included; no CASCADE, no DROP, no warehouse changes.
            cur.execute("TRUNCATE TABLE "+names+" RESTART IDENTITY")
            next_cycle=current_cycle+1
            cur.execute("""
                UPDATE demo_control.dataset_state
                   SET phase='EMPTY',cycle_number=%s,last_run_id=NULL,
                       lock_version=lock_version+1,updated_at=now()
                 WHERE dataset_key='classroom' AND cycle_number=%s
            """,(next_cycle,current_cycle))
            if cur.rowcount!=1: raise RuntimeError("Dataset state update failed")
            cur.execute("""
                INSERT INTO demo_control.reset_audit
                   (dataset_key,previous_cycle,next_cycle,actor,reason,
                    data_tables_cleared,status)
                VALUES ('classroom',%s,%s,%s,%s,25,'SUCCEEDED')
            """,(current_cycle,next_cycle,actor,reason))
    return {"status":"SUCCEEDED","previous_cycle":current_cycle,
            "new_cycle":next_cycle,"phase":"EMPTY",
            "source_tables_cleared":25,
            "historical_archives_preserved":True}


def main():
    parser=argparse.ArgumentParser(description="Reset ONLY Neon demo ER1, never analytics/main")
    parser.add_argument("--confirm",required=True)
    parser.add_argument("--expected-cycle",type=int,required=True)
    parser.add_argument("--reason",required=True)
    args=parser.parse_args()
    db=os.environ.get("NEON_DEMO_DATABASE_URL")
    if not db: raise RuntimeError("Missing protected GitHub Neon demo DB secret")
    actor=os.environ.get("GITHUB_ACTOR","unknown")
    print(reset_source(db,confirmation=args.confirm,
                       expected_cycle=args.expected_cycle,
                       actor=actor,reason=args.reason))


if __name__=="__main__":
    main()
