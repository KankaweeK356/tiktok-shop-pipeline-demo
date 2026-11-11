"""Exercise all seven Source deliveries without touching Neon."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from .generate_classroom_source import BATCHES, build
from .orchestrator import reset, run_batch
from .ml_weekly import run_weekly
from .ml_weekly_serve import serve_monitor_replay
from .ml_scenarios import build_scenarios
from .schema import ROOT


def main() -> None:
    source=ROOT/"output"/"classroom_ci_source"
    workspace=ROOT/"output"/"classroom_ci"
    build(source)
    reset(workspace)
    previous=0
    checks=[]
    for batch in BATCHES:
        result=run_batch(workspace,batch,source)
        if result["status"]!="SUCCESS" or result["functional_fails"]:
            raise AssertionError(f"Delivery did not validate: {batch}")
        with duckdb.connect(str(workspace/"er2.duckdb"),read_only=True) as db:
            orders=db.execute("SELECT COUNT(DISTINCT Source_Order_ID) FROM Fact_Sales_Order_Item").fetchone()[0]
            total,distinct=db.execute("SELECT COUNT(*),COUNT(DISTINCT Source_Order_Item_ID) FROM Fact_Sales_Order_Item").fetchone()
            if total!=distinct or orders<previous:
                raise AssertionError("Incremental delivery lost or duplicated sales items")
            previous=orders
            months=db.execute("SELECT COUNT(*) FROM View_Shop_Monthly_KPI").fetchone()[0]
        checks.append({"source":batch,"paid_orders":orders,"months":months,
                       "validation_passes":result["functional_passes"]})
    if checks[0]["months"]<12 or checks[-1]["months"]<18:
        raise AssertionError("Historical or increment month coverage is incomplete")
    ml_dir=ROOT/"output"/"classroom_ci_ml"
    ml=run_weekly(workspace/"er2.duckdb",source/"ml_marketing_plan.csv",ml_dir)
    monitor=serve_monitor_replay(ml_dir)
    scenarios=build_scenarios(workspace/"er2.duckdb",ml_dir)
    if ml["dataset_rows"]<200 or monitor["status"]!="MONITORED" or scenarios["status"]!="READY":
        raise AssertionError("Warehouse-backed ML or plan inference did not complete")
    if (ml["final_test_window"][1] < "2027-04-01" or
            ml["train_cutoff_week_end"] < "2027-01-01" or
            monitor["forecast_week"] < "2027-04-01"):
        raise AssertionError("Incremental Source did not advance ML Train/Test windows")
    report=ROOT/"output"/"classroom_ci_result.json"
    report.write_text(json.dumps({"deliveries":checks,"source_retained":True,
                                 "ml_rows":ml["dataset_rows"],
                                 "ml_train_through":ml["train_cutoff_week_end"],
                                 "ml_test_window":ml["final_test_window"],
                                 "scenario_options":len(scenarios["grid"])},
                                 ensure_ascii=False,indent=2),encoding="utf-8")
    reset(workspace)
    if (workspace/"er1.sqlite").exists() or (workspace/"er2.duckdb").exists():
        raise AssertionError("Clear did not remove current database and Warehouse")
    if not (source/"initial"/"Fact_Orders.csv").is_file():
        raise AssertionError("Clear removed Source")
    print(report.read_text(encoding="utf-8"))


if __name__=="__main__":
    main()

