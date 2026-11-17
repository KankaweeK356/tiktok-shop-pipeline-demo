"""Generic, schema-driven Data Quality rules shared by Stage 1 (staging gate) and Stage 3.

Nothing here knows about a month, a batch, a SKU or a particular order. The rule
catalog is *derived from the ER1 DBML contract*:

* ``REFERENCE_EXISTS`` for every ``Ref:`` between two Source tables
  (e.g. ``Fact_Order_Items.SKU_ID -> Dim_SKU.SKU_ID``),
* ``NOT_NULL`` for every primary-key / ``not null`` column,
* ``PK_UNIQUE`` for every table primary key (duplicates inside one delivery).

A rule evaluates *every row* of the delivery. The parent universe of a reference
rule is the already-promoted ER1 master data plus the dimension rows delivered by
the same batch. Human corrections are applied only as an *effective overlay* on
the in-memory staging rows - the original CSV is never rewritten.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .er1 import PipelineError, SOURCE_ORDER
from .schema import ROOT, parse_dbml

CATALOG_VERSION = "dq-rules-1"
BLOCKING = "BLOCKING"


class DQBlocked(PipelineError):
    """Blocking data-quality failure. Not a system error: the data must be reviewed."""

    def __init__(self, report: dict):
        self.report = report
        failed = [r["rule_id"] for r in report["results"]
                  if r["status"] == "FAIL" and r["severity"] == BLOCKING]
        first = report["issues"][0] if report["issues"] else {}
        detail = (f"{len(report['issues'])} issue(s); rules={failed[:3]}; "
                  f"first={first.get('table')}#{first.get('pk')}.{first.get('column')}="
                  f"{first.get('invalid_value')!r}")
        super().__init__("DQ_BLOCKED", detail)


@dataclass(frozen=True)
class Rule:
    rule_id: str
    name: str
    kind: str                 # REFERENCE_EXISTS | NOT_NULL | PK_UNIQUE
    table: str
    column: str | None = None
    parent_table: str | None = None
    parent_column: str | None = None
    severity: str = BLOCKING


_CATALOG_CACHE: dict | None = None


def _schema():
    global _CATALOG_CACHE
    if _CATALOG_CACHE is None:
        tables, refs = parse_dbml(ROOT / "schemas" / "ER1_V3.dbml")
        _CATALOG_CACHE = {"tables": {t.name: t for t in tables}, "refs": refs}
    return _CATALOG_CACHE


def build_catalog(tables: Iterable[str] | None = None) -> list[Rule]:
    """Rule catalog generated from the ER1 contract (deterministic order)."""
    schema = _schema()
    source = [t for t in SOURCE_ORDER if tables is None or t in set(tables)]
    allowed = set(source)
    rules: list[Rule] = []
    for table in source:
        meta = schema["tables"][table]
        if meta.pk:
            rules.append(Rule(f"PK_UNIQUE:{table}", f"{table} primary key is unique",
                              "PK_UNIQUE", table, ",".join(meta.pk)))
        for col in meta.columns:
            if col.pk or col.not_null:
                rules.append(Rule(f"NOT_NULL:{table}.{col.name}",
                                  f"{table}.{col.name} is not null", "NOT_NULL", table, col.name))
    for child, ccol, parent, pcol in schema["refs"]:
        if child in allowed and parent in SOURCE_ORDER:
            rules.append(Rule(f"REFERENCE_EXISTS:{child}.{ccol}->{parent}.{pcol}",
                              f"{child}.{ccol} must exist in {parent}.{pcol}",
                              "REFERENCE_EXISTS", child, ccol, parent, pcol))
    return rules


# ---------------------------------------------------------------- helpers

def _safe(value):
    """JSON-safe scalar (pandas/numpy/NaN aware)."""
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return value


def _key(value):
    value = _safe(value)
    return None if value is None else str(value)


def _row_safe(row: dict) -> dict:
    return {k: _safe(v) for k, v in row.items() if not k.startswith("_")}


def pk_of(table: str, row: dict) -> dict:
    return {c: _key(row.get(c)) for c in _schema()["tables"][table].pk}


def issue_key(batch: str, zip_sha256: str, rule_id: str, table: str, pk: dict, column: str) -> str:
    material = json.dumps([batch, zip_sha256 or "", rule_id, table, pk, column],
                          sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def file_name(table: str) -> str:
    return f"{table}.csv"


# ------------------------------------------------------------ corrections

def corrections_path(control_dir: Path, batch: str) -> Path:
    return Path(control_dir) / f"dq_corrections_{batch}.json"


def load_corrections(control_dir: Path, batch: str) -> dict:
    path = corrections_path(control_dir, batch)
    if not path.is_file():
        return {"correction_set_id": None, "corrections": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    return {"correction_set_id": value.get("correction_set_id"),
            "corrections": list(value.get("corrections", []))}


def apply_corrections(staged: dict[str, list[dict]], corrections: list[dict]) -> list[dict]:
    """Overlay approved corrections onto staging rows. Original values must match."""
    applied: list[dict] = []
    indexes: dict[str, dict] = {}
    for item in sorted(corrections, key=lambda c: (c.get("version", 0))):
        table, column = item["table"], item["column"]
        rows = staged.get(table)
        if rows is None:
            raise PipelineError("DQ_CORRECTION_STALE", f"{table} is not part of this delivery")
        if table not in indexes:
            indexes[table] = {json.dumps(pk_of(table, r), sort_keys=True): r for r in rows}
        row = indexes[table].get(json.dumps(item["pk"], sort_keys=True))
        if row is None:
            raise PipelineError("DQ_CORRECTION_STALE", f"{table}{item['pk']} not found")
        if _key(row.get(column)) not in (item.get("original_value"), item.get("new_value")):
            raise PipelineError("DQ_CORRECTION_STALE",
                                f"{table}{item['pk']}.{column} no longer matches the reviewed value")
        row[column] = item["new_value"]
        applied.append({k: item.get(k) for k in ("correction_id", "issue_id", "version", "table",
                                                 "pk", "column", "original_value", "new_value")})
    return applied


# --------------------------------------------------------------- engine

def evaluate(staged: dict[str, list[dict]], *, batch: str, stage: str,
             existing: Callable[[str, str], set[str]] | None = None,
             identity: dict | None = None, corrections: dict | None = None,
             evaluation_kind: str = "GATE", catalog: list[Rule] | None = None,
             max_issues_per_rule: int = 500) -> dict:
    """Evaluate the rule catalog over ``staged`` rows; returns the DQ report."""
    identity = identity or {}
    catalog = catalog if catalog is not None else build_catalog(staged.keys())
    correction_info = corrections or {"correction_set_id": None, "corrections": []}
    applied = apply_corrections(staged, correction_info["corrections"])
    existing = existing or (lambda table, column: set())
    zip_sha = identity.get("zip_sha256", "")
    files = identity.get("files", {})
    universe_cache: dict[tuple, set] = {}

    def universe(parent: str, column: str) -> set:
        cache_key = (parent, column)
        if cache_key not in universe_cache:
            values = {v for v in (_key(r.get(column)) for r in staged.get(parent, [])) if v is not None}
            universe_cache[cache_key] = values | set(existing(parent, column))
        return universe_cache[cache_key]

    ref_by_child: dict[str, list[Rule]] = {}
    for rule in catalog:
        if rule.kind == "REFERENCE_EXISTS":
            ref_by_child.setdefault(rule.table, []).append(rule)

    results, issues = [], []
    executed_at = datetime.now(timezone.utc).isoformat()
    for rule in catalog:
        rows = staged.get(rule.table)
        checked = failed = 0
        found: list[dict] = []
        if rows:
            checked = len(rows)
            if rule.kind == "NOT_NULL":
                for number, row in enumerate(rows, 1):
                    if _key(row.get(rule.column)) in (None, ""):
                        failed += 1
                        found.append(_issue(rule, rule.table, number, row, None, batch, zip_sha, files))
            elif rule.kind == "PK_UNIQUE":
                seen: dict[str, int] = {}
                for number, row in enumerate(rows, 1):
                    token = json.dumps(pk_of(rule.table, row), sort_keys=True)
                    if token in seen:
                        failed += 1
                        found.append(_issue(rule, rule.table, number, row, None, batch, zip_sha, files,
                                            note=f"duplicate of row {seen[token]}"))
                    else:
                        seen[token] = number
            else:  # REFERENCE_EXISTS
                valid = universe(rule.parent_table, rule.parent_column)
                for number, row in enumerate(rows, 1):
                    value = _key(row.get(rule.column))
                    if value is None:
                        continue                     # NULL FK is a NOT_NULL concern
                    if value not in valid:
                        failed += 1
                        found.append(_issue(rule, rule.table, number, row, value, batch, zip_sha, files,
                                            staged=staged, siblings=ref_by_child.get(rule.table, [])))
        status = "NOT_CHECKED" if checked == 0 else ("FAIL" if failed else "PASS")
        results.append({
            "rule_id": rule.rule_id, "rule_name": rule.name, "rule_kind": rule.kind,
            "input_table": rule.table, "input_column": rule.column,
            "parent_table": rule.parent_table, "parent_column": rule.parent_column,
            "checked_rows": checked, "failed_rows": failed, "threshold": 0,
            "severity": rule.severity, "status": status,
            "source_file": file_name(rule.table),
            "source_file_sha256": (files.get(file_name(rule.table)) or {}).get("sha256"),
            "evaluation_kind": evaluation_kind, "stage": stage, "executed_at": executed_at,
        })
        issues.extend(found[:max_issues_per_rule])
    blocking = [r for r in results if r["status"] == "FAIL" and r["severity"] == BLOCKING]
    return {
        "rule_catalog_version": CATALOG_VERSION, "batch": batch, "stage": stage,
        "evaluation_kind": evaluation_kind, "executed_at": executed_at,
        "source": {"source_version": identity.get("source_version"),
                   "zip_sha256": zip_sha or None, "lock_status": identity.get("lock_status")},
        "correction_set_id": correction_info.get("correction_set_id"),
        "corrections_applied": applied,
        "results": results, "issues": issues,
        "summary": {"rules": len(results),
                    "passed": sum(r["status"] == "PASS" for r in results),
                    "failed": sum(r["status"] == "FAIL" for r in results),
                    "not_checked": sum(r["status"] == "NOT_CHECKED" for r in results),
                    "checked_rows": sum(r["checked_rows"] for r in results),
                    "failed_rows": sum(r["failed_rows"] for r in results),
                    "blocking_failed_rules": len(blocking),
                    "blocked": bool(blocking)},
    }


def _issue(rule: Rule, table: str, number: int, row: dict, invalid, batch: str, zip_sha: str,
           files: dict, *, staged: dict | None = None, siblings: list | None = None,
           note: str | None = None) -> dict:
    pk = pk_of(table, row)
    column = rule.column if rule.kind != "PK_UNIQUE" else ",".join(pk)
    item = {
        "issue_key": issue_key(batch, zip_sha, rule.rule_id, table, pk, column or ""),
        "rule_id": rule.rule_id, "severity": rule.severity, "batch": batch,
        "table": table, "source_file": file_name(table),
        "source_file_sha256": (files.get(file_name(table)) or {}).get("sha256"),
        "source_zip_sha256": zip_sha or None,
        "source_row_no": number, "pk": pk, "column": column,
        "invalid_value": invalid, "row_snapshot": _row_snapshot(row),
        "parent_table": rule.parent_table, "parent_column": rule.parent_column,
        "note": note,
    }
    if staged is not None and siblings:
        context = {}
        schema = _schema()
        for other in siblings:
            if other.column == rule.column:
                continue
            value = _key(row.get(other.column))
            if value is None:
                continue
            match = next((r for r in staged.get(other.parent_table, [])
                          if _key(r.get(other.parent_column)) == value), None)
            if match is not None:
                context[f"{other.parent_table}"] = _row_snapshot(match)
        item["context"] = context
    return item


def _row_snapshot(row: dict) -> dict:
    return _row_safe(row)


# ---------------------------------------------------- universe providers

def sqlite_universe(conn) -> Callable[[str, str], set[str]]:
    """Existing (already promoted) ER1 values, read from the processing workspace."""
    def lookup(table: str, column: str) -> set[str]:
        try:
            cur = conn.execute(f'SELECT DISTINCT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL')
        except Exception:                        # table not created yet (first delivery)
            return set()
        return {str(r[0]) for r in cur.fetchall()}
    return lookup


def evaluate_raw_snapshot(raw_dir: Path, *, batch: str, stage: str = "transform",
                          identity: dict | None = None) -> dict:
    """Stage 3 defense in depth: same reference/PK rules over the ER1 Raw Parquet snapshot."""
    import pandas as pd
    catalog = [r for r in build_catalog() if r.kind in ("REFERENCE_EXISTS", "PK_UNIQUE")]
    needed = {r.table for r in catalog} | {r.parent_table for r in catalog if r.parent_table}
    tables: dict[str, list[dict]] = {}
    for table in needed:
        path = Path(raw_dir) / f"{table}.parquet"
        if path.is_file():
            frame = pd.read_parquet(path, engine="pyarrow")
            tables[table] = frame.where(frame.notna(), None).to_dict("records")
    catalog = [r for r in catalog if r.table in tables and (r.parent_table is None or r.parent_table in tables)]
    return evaluate(tables, batch=batch, stage=stage, identity=identity,
                    evaluation_kind="DEFENSE", catalog=catalog)


def write_report(governance_dir: Path, report: dict) -> Path:
    folder = Path(governance_dir) / "dq"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{report['batch']}_{report['stage']}_{report['evaluation_kind'].lower()}_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def summary_for_receipt(report: dict) -> dict:
    """Compact, count-only view stored with the stage receipt."""
    return {**report["summary"], "rule_catalog_version": report["rule_catalog_version"],
            "correction_set_id": report.get("correction_set_id"),
            "corrections_applied": len(report.get("corrections_applied", [])),
            "evaluation_kind": report["evaluation_kind"]}
