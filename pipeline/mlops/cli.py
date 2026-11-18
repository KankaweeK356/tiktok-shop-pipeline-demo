"""Local / CI entry point: build the feature set and a training run from a Published ER2 snapshot.

    python -m pipeline.mlops.cli --er2 er2_2026-05.duckdb --target-month 2026-06 --kind HISTORICAL_EVALUATION \
        --source-run-id <published run id> --out ./mlops_out [--actual-er2 er2_2026-06.duckdb]

The ER2 snapshot must be the one that was PUBLISHED at the cutoff month (it then contains no later data by construction).
`--actual-er2` (a later snapshot) is only used for a labelled post-hoc evaluation of the target month, never as a feature.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import features as ft
from . import training as tr
from .definitions import DEFAULT_PREFIX, GROUPS
from .store import LocalDirStore


def run(er2: Path, target_month: str, kind: str, source_run_id: str | None, out: Path, actual_er2: Path | None = None,
        official_forecast_id: str | None = None, prefix: str = DEFAULT_PREFIX) -> dict:
    rows = ft.read_published_marketing_months(er2)
    source = {"source_run_id": source_run_id or "local", "warehouse_file": er2.name, "warehouse_file_sha256": ft.file_sha256(er2),
              "published_through": max(r["month"] for r in rows), "rows_read": len(rows)}
    actual = None
    if actual_er2 is not None:
        later = ft.read_published_marketing_months(actual_er2)
        actual = {g: sum(r["net_revenue"] for r in later if r["month"] == target_month and r["group"] == g) for g in GROUPS}
        source["actual_warehouse_file_sha256"] = ft.file_sha256(actual_er2)
    bundle = tr.run_experiment(rows, target_month, kind=kind, source=source, actual_by_group=actual, official_forecast_id=official_forecast_id)
    result = tr.persist(LocalDirStore(out), bundle, prefix=prefix)
    return {**result, "out": str(out)}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--er2", required=True, type=Path)
    p.add_argument("--target-month", required=True)
    p.add_argument("--kind", default="HISTORICAL_EVALUATION", choices=tr.KINDS)
    p.add_argument("--source-run-id")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--actual-er2", type=Path)
    p.add_argument("--official-forecast-id")
    args = p.parse_args()
    print(json.dumps(run(args.er2, args.target_month, args.kind, args.source_run_id, args.out, args.actual_er2, args.official_forecast_id), indent=2))


if __name__ == "__main__":
    main()
