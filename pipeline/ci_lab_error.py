"""Real isolated failure/retry suite plus rollback-only Neon FK check."""
from __future__ import annotations

import json
import os
import uuid

import psycopg

from .demo_tests import error_suite
from .schema import ROOT


def neon_fk_recovery(url: str) -> dict:
    probe_sku = "ERROR_TEST_" + uuid.uuid4().hex
    missing_group = "MISSING_GROUP_" + uuid.uuid4().hex
    with psycopg.connect(url) as db:
        try:
            with db.cursor() as cur:
                cur.execute('SELECT "Product_Group_ID" FROM demo_er1."Dim_Product_Group" LIMIT 1')
                known = cur.fetchone()
                if not known:
                    raise RuntimeError("Neon has no product group to verify a successful retry")
                cur.execute('SAVEPOINT before_bad_sku')
                detected = False
                try:
                    cur.execute('INSERT INTO demo_er1."Dim_SKU" '
                                '("SKU_ID","Product_Group_ID") VALUES (%s,%s)',
                                (probe_sku, missing_group))
                except psycopg.errors.ForeignKeyViolation:
                    detected = True
                    cur.execute('ROLLBACK TO SAVEPOINT before_bad_sku')
                if not detected:
                    raise RuntimeError("Neon failed to reject unknown product group")
                cur.execute('INSERT INTO demo_er1."Dim_SKU" '
                            '("SKU_ID","Product_Group_ID") VALUES (%s,%s)',
                            (probe_sku, known[0]))
                cur.execute('SELECT COUNT(*) FROM demo_er1."Dim_SKU" WHERE "SKU_ID"=%s',
                            (probe_sku,))
                retry_ok = cur.fetchone()[0] == 1
                if not retry_ok:
                    raise RuntimeError("Valid SKU retry failed")
        finally:
            db.rollback()
    with psycopg.connect(url) as check:
        with check.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM demo_er1."Dim_SKU" WHERE "SKU_ID"=%s',
                        (probe_sku,))
            if cur.fetchone()[0] != 0:
                raise RuntimeError("Error test left a row in Neon")
    return {"case": "NEON_FK", "stage": "Database", "before": "FK rejected",
            "after": "Valid retry passed", "passed": True,
            "rollback": "All probe changes rolled back; no business row written"}


def main() -> None:
    url = os.environ.pop("NEON_DEMO_DATABASE_URL", "")
    if not url:
        raise RuntimeError("Neon Lab credential missing")
    cases = error_suite(ROOT / "output" / "classroom_error")
    if not cases["passed"].all():
        raise RuntimeError("Local pipeline error/retry suite failed")
    neon_case = neon_fk_recovery(url)
    output = {"status": "SUCCESS", "mode": "REAL_ISOLATED_ERROR_TEST",
              "cases": json.loads(cases.to_json(orient="records")),
              "neon_case": neon_case}
    path = ROOT / "output" / "classroom_error_result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cases": len(output["cases"]), "neon_fk_passed": True}))


if __name__ == "__main__":
    main()
