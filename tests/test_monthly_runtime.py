"""Exercise monthly deliveries through the real offline ETL, without live writes."""
import sqlite3
import duckdb
from pipeline.generate_classroom_source import build, BATCHES
from pipeline.orchestrator import run_batch


def test_ten_months_and_retry_do_not_duplicate(tmp_path, monkeypatch):
    monkeypatch.delenv("NEON_DEMO_DATABASE_URL", raising=False)
    source = tmp_path / "source"
    workspace = tmp_path / "workspace"
    build(source)
    previous = 0
    for month, batch in enumerate(BATCHES, 1):
        result = run_batch(workspace, batch, source_root=source)
        assert result["status"] == "SUCCESS"
        assert result["functional_fails"] == 0
        with sqlite3.connect(workspace / "er1.sqlite") as db:
            count = db.execute("SELECT COUNT(*) FROM Fact_Orders").fetchone()[0]
            months = db.execute("SELECT DISTINCT substr(Order_Created_At,1,7) FROM Fact_Orders ORDER BY 1").fetchall()
        assert count > previous
        assert months == [(f"2026-{i:02d}",) for i in range(1, month + 1)]
        replay = run_batch(workspace, batch, source_root=source)
        assert replay["status"] == "SUCCESS"
        with sqlite3.connect(workspace / "er1.sqlite") as db:
            assert db.execute("SELECT COUNT(*) FROM Fact_Orders").fetchone()[0] == count
        with duckdb.connect(str(workspace / "er2.duckdb"), read_only=True) as db:
            n, unique = db.execute("SELECT COUNT(*),COUNT(DISTINCT Source_Order_Item_ID) FROM Fact_Sales_Order_Item").fetchone()
            assert n == unique
        previous = count
