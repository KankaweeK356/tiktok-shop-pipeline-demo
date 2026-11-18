"""Serialise writers of one monitoring stream across worker instances (Postgres advisory lock; needs no schema change).
The object store itself only has check-then-write semantics, so two simultaneous evaluations could otherwise race."""
from __future__ import annotations

import contextlib


@contextlib.contextmanager
def stream_lock(database_url: str, stream: str):
    import psycopg
    with psycopg.connect(database_url) as db:
        db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("mlops-monitoring:" + stream,))
        yield                                                                    # the lock is held until this transaction ends
