"""Champion-Challenger monitoring rules (locked by the project owner). Synthetic rows are TEST FIXTURES for the rules only."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from pipeline import monthly_forecast as mf
from pipeline.mlops import monitoring as mon
from pipeline.mlops import training as tr
from pipeline.mlops.store import LocalDirStore
from tests.test_mlops_feature_store import SRC, make_rows

G = ["PG01", "PG02", "PG03", "PG04", "PG05"]
T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


def months(n, start="2026-06"):
    return [mf.month_add(start, i) for i in range(n)]


def shadow_for(month, fid, b_err, m_err, *, per_group_ml=None, created=None, kind="OFFICIAL_LINKED", with_ml=True):
    """Actual is 20,000 per group. Baseline / ML shop error = b_err / m_err (spread equally unless per_group_ml is given)."""
    cutoff = mf.month_add(month, -1)
    ml_groups = per_group_ml or {g: 20000 + m_err / 5 for g in G}
    return {"kind": kind, "target_month": month, "official_forecast_id": fid, "training_run_id": "run-" + month, "created_at": (created or T0).isoformat(),
            "cutoff_month": cutoff, "data_cutoff": cutoff + "-28", "feature_version": "mlops-features-1",
            "baseline": {"model": mon.CHAMPION, "model_version": "b1", "groups": {g: 20000 + b_err / 5 for g in G}, "shop": 100000 + b_err},
            "ml": {"model": mon.CHALLENGER, "model_version": "r1", "groups": ml_groups, "shop": sum(ml_groups.values())} if with_ml else None}


def row(month, b_err, m_err, **kw):
    fid = "fc-" + month
    return mon.evaluate_month(month=month, forecast={"forecast_run_id": fid, "method_type": "BASELINE", "model_name": "trailing_3_month_mean"},
                              shadow=kw.pop("shadow", None) or shadow_for(month, fid, b_err, m_err, **kw), actual_by_group={g: 20000.0 for g in G},
                              actual_published_at=(T0 + timedelta(days=1)).isoformat(), actual_run_id="r-" + month)


def series(pairs, **kw):
    return mon.summarize([row(m, b, e, **kw) for m, (b, e) in zip(months(len(pairs)), pairs)], cycle=1)


def test_evidence_levels_are_locked():
    assert [mon.evidence_level(n) for n in (0, 2, 3, 5, 6, 9)] == ["INSUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE", "PRELIMINARY", "PRELIMINARY", "ADEQUATE", "ADEQUATE"]
    assert series([(8000, 6000)] * 2)["recommendation"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert series([(8000, 6000)] * 4)["recommendation"]["status"] == "PRELIMINARY_NOT_ASSESSED"          # good numbers, still not assessed
    assert series([(8000, 6000)] * 5)["counted_months"] == 5


def test_cumulative_wape_is_total_error_over_total_actual_not_the_mean_of_monthly_wape():
    rows = [row("2026-06", 10000, 0), row("2026-07", 1000, 0)]
    rows[1]["actual"]["shop"] = 20000.0; rows[1]["baseline"]["shop_abs_error"] = 1000.0            # a smaller month: weights must differ
    s = mon.summarize(rows, cycle=1)
    assert s["cumulative"]["baseline"]["wape_pct"] == pytest.approx(100 * 11000 / 120000)
    assert s["cumulative"]["baseline"]["wape_pct"] != pytest.approx((10.0 + 5.0) / 2)
    assert s["cumulative"]["baseline"]["abs_error_total"] == 11000


def test_recommendation_requires_every_condition_and_reports_each_reason():
    ok = series([(8000, 6000)] * 6)                                    # gap exactly 2.0 pp, ML wins all 6, no group worse
    r = ok["recommendation"]
    assert r["status"] == "RECOMMEND_REVIEW" and all(x["passed"] for x in r["rules"]) and ok["evidence_level"] == "ADEQUATE"
    assert r["human_decision_required"] is True and r["auto_switch_champion"] is False and r["auto_retrain"] is False
    below = series([(8000, 6020)] * 6)["recommendation"]               # gap 1.98 pp => fails only the gap rule
    assert below["status"] == "NOT_RECOMMENDED" and [x["rule"] for x in below["rules"] if not x["passed"]] == ["CUMULATIVE_WAPE_GAP"]
    four = series([(8000, 6000)] * 4 + [(6000, 9000)] * 2 + [], )      # last six months: ML wins 4, loses 2 -> wins ok, but gap negative-ish check below
    assert [x for x in four["recommendation"]["rules"] if x["rule"] == "MONTHLY_WINS"][0]["passed"] is True
    three = series([(8000, 6000)] * 3 + [(6000, 6500)] * 3)["recommendation"]                  # only 3 wins of 6
    wins = [x for x in three["rules"] if x["rule"] == "MONTHLY_WINS"][0]
    assert wins["passed"] is False and wins["detail"] == "3 จาก 6 เดือนล่าสุด" and three["status"] == "NOT_RECOMMENDED"


def test_monthly_wins_window_is_the_latest_six_months():
    s = series([(6000, 9000)] * 3 + [(8000, 6000)] * 6)               # 9 months: first 3 lose, latest 6 all win
    assert [x for x in s["recommendation"]["rules"] if x["rule"] == "MONTHLY_WINS"][0]["detail"] == "6 จาก 6 เดือนล่าสุด"


def test_group_guardrail_boundary_is_five_points():
    def groups(extra):                                                  # ML concentrates error in PG01; shop WAPE of ML stays far below baseline
        g = {k: 20000.0 for k in G}; g["PG01"] = 20000.0 + extra; g["PG02"] = 20000.0 - extra
        return g
    def run(extra):
        rows = [row(m, 10000, 0, per_group_ml=groups(extra)) for m in months(6)]
        return mon.summarize(rows, cycle=1)
    # baseline group WAPE is 10% (2000 error per group of 20000); ML group PG01 WAPE = extra/20000
    ok = run(2000 + 0.05 * 20000)                                       # PG01 gap exactly +5.00 pp -> allowed
    bad = run(2000 + 0.0501 * 20000)                                    # +5.01 pp -> fails
    assert [x for x in ok["recommendation"]["rules"] if x["rule"] == "GROUP_GUARDRAIL"][0]["passed"] is True
    assert [x for x in bad["recommendation"]["rules"] if x["rule"] == "GROUP_GUARDRAIL"][0]["passed"] is False
    assert bad["recommendation"]["status"] == "NOT_RECOMMENDED"


def test_only_pre_actual_complete_pairs_are_counted_and_every_exclusion_has_a_reason():
    fid = "fc-2026-06"
    base = dict(month="2026-06", forecast={"forecast_run_id": fid, "method_type": "BASELINE"}, actual_by_group={g: 20000.0 for g in G},
                actual_published_at=(T0 + timedelta(days=1)).isoformat(), actual_run_id="r")
    cases = {
        "NO_SHADOW": None,
        "SHADOW_NOT_BOUND_TO_SEALED_FORECAST": shadow_for("2026-06", "other", 1, 1),
        "ML_OR_BASELINE_MISSING": shadow_for("2026-06", fid, 1, 1, with_ml=False),
        "SHADOW_NOT_RECORDED_BEFORE_ACTUAL": shadow_for("2026-06", fid, 1, 1, created=T0 + timedelta(days=2)),
    }
    for reason, shadow in cases.items():
        r = mon.evaluate_month(shadow=shadow, **base)
        assert r["status"] == "EXCLUDED" and r["exclusion_reason"] == reason
    hist = mon.evaluate_month(shadow=shadow_for("2026-06", fid, 1, 1, kind="HISTORICAL_EVALUATION"), **base)
    assert hist["exclusion_reason"] == "SHADOW_NOT_BOUND_TO_SEALED_FORECAST"                       # a backtest/historical run can never be counted
    assert mon.evaluate_month(shadow=shadow_for("2026-06", fid, 1, 1), **{**base, "actual_by_group": {**{g: 1.0 for g in G[:4]}, "PG05": None}})["exclusion_reason"] == "ACTUAL_INCOMPLETE"
    assert mon.evaluate_month(shadow=shadow_for("2026-07", fid, 1, 1), **base)["exclusion_reason"] == "SHADOW_TARGET_MISMATCH"
    s = mon.summarize([mon.evaluate_month(shadow=v, **base) for v in cases.values()], cycle=1)
    assert s["counted_months"] == 0 and len(s["excluded"]) == 4 and s["evidence_level"] == "INSUFFICIENT_EVIDENCE"


def test_error_sign_and_ape_use_the_same_actual_for_both_models():
    r = row("2026-06", -5000, 3000)
    assert r["baseline"]["shop_error"] == -5000 and r["ml"]["shop_error"] == 3000          # forecast - actual
    assert r["baseline"]["shop_ape_pct"] == pytest.approx(5.0) and r["ml"]["shop_ape_pct"] == pytest.approx(3.0)
    assert r["actual"]["shop"] == 100000 and set(r["ml"]["group_error"]) == set(G)


# ------------------------------------------------------------------ end to end with the real training run + write-once store
def real_shadow_store(tmp_path, fid="fc-real"):
    rows = make_rows(5)
    b = tr.run_experiment(rows, "2026-06", kind="OFFICIAL_LINKED", source=SRC, official_forecast_id=fid)
    store = LocalDirStore(tmp_path)
    return rows, b, store, tr.persist(store, b)


def actual_rows_for(month, net=20000.0):
    return [{"month": month, "group": g, "net_revenue": net} for g in G]


def test_training_run_writes_a_shadow_with_all_audit_fields_and_a_forecast_pointer(tmp_path):
    _rows, b, store, out = real_shadow_store(tmp_path)
    shadow = json.loads(store.get(f"{out['run_path']}/shadow_forecast.json"))
    for key in ("target_month", "created_at", "data_cutoff", "feature_version", "official_forecast_id", "cutoff_month"):
        assert shadow[key]
    assert shadow["data_cutoff"] == "2026-05-31" and shadow["baseline"]["model_version"] and shadow["ml"]["model_version"]
    assert set(shadow["baseline"]["groups"]) == set(G) and set(shadow["ml"]["groups"]) == set(G) and shadow["ml"]["shop"] == pytest.approx(sum(shadow["ml"]["groups"].values()), abs=0.02)
    assert store.exists("vercel-lab/ml/monitoring/by_forecast/fc-real.json")
    hist = tr.run_experiment(make_rows(5), "2026-06", kind="HISTORICAL_EVALUATION", source=SRC, official_forecast_id="fc-hist")
    tr.persist(store, hist)
    assert not store.exists("vercel-lab/ml/monitoring/by_forecast/fc-hist.json")                 # only an official-linked shadow is ever looked up


def test_record_month_is_automatic_write_once_and_ignores_historical_runs(tmp_path):
    _rows, b, store, out = real_shadow_store(tmp_path)
    created = datetime.fromisoformat(b["shadow"]["created_at"])
    res = mon.record_month(store, cycle=3, month="2026-06", forecast={"forecast_run_id": "fc-real", "method_type": "BASELINE"}, actual_rows=actual_rows_for("2026-06"),
                           actual_published_at=(created + timedelta(minutes=5)).isoformat(), actual_run_id="run-june")
    assert res["status"] == "EVALUATED" and res["counted_months"] == 1 and res["evidence_level"] == "INSUFFICIENT_EVIDENCE"
    assert store.exists("vercel-lab/ml/monitoring/3/evaluations/2026-06.json") and store.exists("vercel-lab/ml/monitoring/3/summary/through=2026-06.json")
    again = mon.record_month(store, cycle=3, month="2026-06", forecast={"forecast_run_id": "fc-real", "method_type": "BASELINE"}, actual_rows=actual_rows_for("2026-06", 1.0),
                             actual_published_at=(created + timedelta(minutes=9)).isoformat(), actual_run_id="run-june")
    assert again["status"] == "ALREADY_RECORDED"                                                     # never rewritten
    stored = json.loads(store.get("vercel-lab/ml/monitoring/3/evaluations/2026-06.json"))
    assert stored["actual"]["shop"] == 100000.0
    late = mon.record_month(store, cycle=3, month="2026-07", forecast={"forecast_run_id": "fc-none", "method_type": "BASELINE"}, actual_rows=actual_rows_for("2026-07"),
                            actual_published_at=T0.isoformat(), actual_run_id="run-july")
    assert late["status"] == "EXCLUDED" and late["exclusion_reason"] == "NO_SHADOW"
    summary = json.loads(store.get("vercel-lab/ml/monitoring/3/summary/through=2026-07.json"))
    assert summary["counted_months"] == 1 and [e["month"] for e in summary["excluded"]] == ["2026-07"]
    # published BEFORE the shadow existed (e.g. regenerated after the actual) -> excluded
    _r2, b2, store2, _o2 = real_shadow_store(tmp_path / "b", fid="fc-late")
    early = datetime.fromisoformat(b2["shadow"]["created_at"]) - timedelta(minutes=1)
    r = mon.record_month(store2, cycle=1, month="2026-06", forecast={"forecast_run_id": "fc-late", "method_type": "BASELINE"}, actual_rows=actual_rows_for("2026-06"),
                         actual_published_at=early.isoformat(), actual_run_id="x")
    assert r["exclusion_reason"] == "SHADOW_NOT_RECORDED_BEFORE_ACTUAL" and r["counted_months"] == 0


def test_monitoring_never_modifies_official_selection_or_forecast():
    rows = make_rows(5)
    core = [{"month": r["month"], "group": r["group"], "net_revenue": r["net_revenue"]} for r in rows]
    before = mf.generate_forecast(core, "2026-06")
    series([(8000, 6000)] * 6)
    assert mf.generate_forecast(core, "2026-06") == before
