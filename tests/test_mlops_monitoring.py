"""Champion-Challenger monitoring rules (locked by the project owner). Synthetic rows are TEST FIXTURES for the rules only."""
import json
from pathlib import Path
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


def baseline_groups(b_err):
    return {g: 20000 + b_err / 5 for g in G}


def sealed_forecast(month, b_err, *, model="trailing_3_month_mean", method="BASELINE"):
    return {"forecast_run_id": "fc-" + month, "method_type": method, "model_name": model, "results": baseline_groups(b_err)}


def shadow_for(month, fid, b_err, m_err, *, per_group_ml=None, created=None, kind="OFFICIAL_LINKED", with_ml=True, naive_err=None):
    """Actual is 20,000 per group. Official baseline / ML shop error = b_err / m_err (spread equally unless per_group_ml is given)."""
    cutoff = mf.month_add(month, -1)
    ml_groups = per_group_ml or {g: 20000 + m_err / 5 for g in G}
    def base(name, err):
        return {"model": name, "model_version": "b1", "groups": baseline_groups(err), "shop": 100000 + err}
    return {"kind": kind, "target_month": month, "official_forecast_id": fid, "training_run_id": "run-" + month, "created_at": (created or T0).isoformat(),
            "cutoff_month": cutoff, "data_cutoff": cutoff + "-28", "feature_version": "mlops-features-1",
            "baselines": {"baseline_trailing_3_month_mean": base("baseline_trailing_3_month_mean", b_err),
                          "baseline_naive_previous_month": base("baseline_naive_previous_month", b_err + 7777 if naive_err is None else naive_err)},
            "ml": {"model": mon.CHALLENGER, "model_version": "r1", "groups": ml_groups, "shop": sum(ml_groups.values())} if with_ml else None}


def row(month, b_err, m_err, **kw):
    fid = "fc-" + month
    forecast = kw.pop("forecast", None) or sealed_forecast(month, b_err)
    return mon.evaluate_month(month=month, forecast=forecast, shadow=kw.pop("shadow", None) or shadow_for(month, fid, b_err, m_err, **kw), actual_by_group={g: 20000.0 for g in G},
                              actual_published_at=(T0 + timedelta(days=1)).isoformat(), actual_run_id="r-" + month)


def series(pairs, **kw):
    return mon.summarize([row(m, b, e, **kw) for m, (b, e) in zip(months(len(pairs)), pairs)], stream="lab-cycle-1")


def test_evidence_levels_are_locked():
    assert [mon.evidence_level(n) for n in (0, 2, 3, 5, 6, 9)] == ["INSUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE", "PRELIMINARY", "PRELIMINARY", "ADEQUATE", "ADEQUATE"]
    assert series([(8000, 6000)] * 2)["recommendation"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert series([(8000, 6000)] * 4)["recommendation"]["status"] == "PRELIMINARY_NOT_ASSESSED"          # good numbers, still not assessed
    assert series([(8000, 6000)] * 5)["counted_months"] == 5


def test_cumulative_wape_is_total_error_over_total_actual_not_the_mean_of_monthly_wape():
    rows = [row("2026-06", 10000, 0), row("2026-07", 1000, 0)]
    rows[1]["actual"]["shop"] = 20000.0; rows[1]["baseline"]["shop_abs_error"] = 1000.0            # a smaller month: weights must differ
    s = mon.summarize(rows, stream="lab-cycle-1")
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
        return mon.summarize(rows, stream="lab-cycle-1")
    # baseline group WAPE is 10% (2000 error per group of 20000); ML group PG01 WAPE = extra/20000
    ok = run(2000 + 0.05 * 20000)                                       # PG01 gap exactly +5.00 pp -> allowed
    bad = run(2000 + 0.0501 * 20000)                                    # +5.01 pp -> fails
    assert [x for x in ok["recommendation"]["rules"] if x["rule"] == "GROUP_GUARDRAIL"][0]["passed"] is True
    assert [x for x in bad["recommendation"]["rules"] if x["rule"] == "GROUP_GUARDRAIL"][0]["passed"] is False
    assert bad["recommendation"]["status"] == "NOT_RECOMMENDED"


def test_only_pre_actual_complete_pairs_are_counted_and_every_exclusion_has_a_reason():
    fid = "fc-2026-06"
    forecast = sealed_forecast("2026-06", 1)
    base = dict(month="2026-06", forecast=forecast, actual_by_group={g: 20000.0 for g in G},
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
    s = mon.summarize([mon.evaluate_month(shadow=v, **base) for v in cases.values()], stream="lab-cycle-1")
    assert s["counted_months"] == 0 and len(s["excluded"]) == 4 and s["evidence_level"] == "INSUFFICIENT_EVIDENCE"


def test_champion_is_the_official_baseline_actually_sealed_each_month():
    naive = row("2026-06", 3000, 2000, forecast=sealed_forecast("2026-06", 5555, model="naive_previous_month"), naive_err=5555)
    assert naive["status"] == "EVALUATED" and naive["champion_model"] == "baseline_naive_previous_month"
    assert naive["baseline"]["shop_error"] == 5555 and naive["baseline"]["shop_abs_error"] == 5555      # the sealed values, not trailing-3 (3000)
    tr3 = row("2026-07", 3000, 2000)
    assert tr3["champion_model"] == "baseline_trailing_3_month_mean" and tr3["baseline"]["shop_error"] == 3000
    s = mon.summarize([naive, tr3], stream="s")
    assert s["champion_models_by_month"] == {"2026-06": "baseline_naive_previous_month", "2026-07": "baseline_trailing_3_month_mean"}
    assert s["pair"]["champion"] == "OFFICIAL_BASELINE_OF_EACH_MONTH"


def test_official_must_be_a_baseline_and_must_match_its_shadow():
    ml_official = row("2026-06", 1000, 500, forecast=sealed_forecast("2026-06", 1000, method="ML", model="ridge_pooled_group_month"))
    assert ml_official["status"] == "EXCLUDED" and ml_official["exclusion_reason"] == "OFFICIAL_NOT_BASELINE"
    tampered = sealed_forecast("2026-06", 1000); tampered["results"]["PG01"] += 5
    assert row("2026-06", 1000, 500, forecast=tampered)["exclusion_reason"] == "OFFICIAL_BASELINE_MISMATCH"


def test_error_sign_and_ape_use_the_same_actual_for_both_models():
    r = row("2026-06", -5000, 3000)
    assert r["baseline"]["shop_error"] == -5000 and r["ml"]["shop_error"] == 3000          # forecast - actual
    assert r["baseline"]["shop_ape_pct"] == pytest.approx(5.0) and r["ml"]["shop_ape_pct"] == pytest.approx(3.0)
    assert r["actual"]["shop"] == 100000 and set(r["ml"]["group_error"]) == set(G)


def test_recommendation_carries_its_evidence_and_offers_no_way_to_change_the_champion():
    r = series([(8000, 6000)] * 6)["recommendation"]
    assert r["status"] == "RECOMMEND_REVIEW" and r["champion_change_function_in_system"] is False and r["auto_switch_champion"] is False
    assert len(r["evidence"]["counted_months"]) == 6 and len(r["evidence"]["official_forecast_ids"]) == 6 and len(r["evidence"]["shadow_training_runs"]) == 6
    assert "ไม่มีฟังก์ชันเปลี่ยน Champion" in r["message"]


def test_data_origin_is_recorded_and_validated():
    assert mon.summarize([], stream="s", data_origin="SYNTHETIC_FIXTURE")["data_origin"] == "SYNTHETIC_FIXTURE"
    with pytest.raises(ValueError):
        mon.summarize([], stream="s", data_origin="made-up")


def test_month_arithmetic_crosses_years_and_nothing_is_tied_to_2026():
    assert mon.month_add("2026-12", 1) == "2027-01" and mon.month_add("2027-01", -1) == "2026-12" and mon.month_add("2026-11", 14) == "2028-01"
    ms = ["2026-11", "2026-12", "2027-01", "2027-02", "2027-03", "2027-04"]
    rows = [row(m, 8000, 6000) for m in ms]
    assert all(r["status"] == "EVALUATED" for r in rows)                          # cutoff check works across the year boundary
    s = mon.summarize(rows, stream="long")
    assert s["through_month"] == "2027-04" and s["counted_months"] == 6 and s["recommendation"]["status"] == "RECOMMEND_REVIEW"


# ------------------------------------------------------------------ end to end with the real training run + write-once store
def real_shadow_store(tmp_path, fid="fc-real", month="2026-06", rows=None):
    rows = rows or make_rows(5)
    b = tr.run_experiment(rows, month, kind="OFFICIAL_LINKED", source=SRC, official_forecast_id=fid)
    store = LocalDirStore(tmp_path)
    return rows, b, store, tr.persist(store, b)


def official_from(b, fid):
    """What the worker would load from Neon: the sealed official forecast (policy: always a baseline)."""
    logic = b["evaluation"]["official_logic_result"]
    return {"forecast_run_id": fid, "method_type": logic["method_type"], "model_name": logic["model_name"], "results": logic["predictions"]}


def actual_rows_for(month, net=20000.0):
    return [{"month": month, "group": g, "net_revenue": net} for g in G]


def test_training_run_writes_a_shadow_with_all_audit_fields_and_a_forecast_pointer(tmp_path):
    _rows, b, store, out = real_shadow_store(tmp_path)
    shadow = json.loads(store.get(f"{out['run_path']}/shadow_forecast.json"))
    for key in ("target_month", "created_at", "data_cutoff", "feature_version", "official_forecast_id", "cutoff_month"):
        assert shadow[key]
    assert shadow["data_cutoff"] == "2026-05-31" and set(shadow["baselines"]) == {"baseline_trailing_3_month_mean", "baseline_naive_previous_month"}
    assert all(v["model_version"] for v in shadow["baselines"].values()) and shadow["ml"]["model_version"]
    assert set(shadow["ml"]["groups"]) == set(G) and shadow["ml"]["shop"] == pytest.approx(sum(shadow["ml"]["groups"].values()), abs=0.02)
    assert store.exists("vercel-lab/ml/monitoring/by_forecast/fc-real.json")
    hist = tr.run_experiment(make_rows(5), "2026-06", kind="HISTORICAL_EVALUATION", source=SRC, official_forecast_id="fc-hist")
    tr.persist(store, hist)
    assert not store.exists("vercel-lab/ml/monitoring/by_forecast/fc-hist.json")                 # only an official-linked shadow is ever looked up


def test_record_month_is_automatic_write_once_and_ignores_historical_runs(tmp_path):
    _rows, b, store, out = real_shadow_store(tmp_path)
    created = datetime.fromisoformat(b["shadow"]["created_at"])
    forecast = official_from(b, "fc-real")
    res = mon.record_month(store, stream="lab-cycle-3", cycle=3, month="2026-06", forecast=forecast, actual_rows=actual_rows_for("2026-06"),
                           actual_published_at=(created + timedelta(minutes=5)).isoformat(), actual_run_id="run-june", data_origin="SYNTHETIC_FIXTURE")
    assert res["status"] == "EVALUATED" and res["counted_months"] == 1 and res["evidence_level"] == "INSUFFICIENT_EVIDENCE"
    assert store.exists("vercel-lab/ml/monitoring/lab-cycle-3/evaluations/2026-06.json") and store.exists("vercel-lab/ml/monitoring/lab-cycle-3/summary/through=2026-06.json")
    assert json.loads(store.get("vercel-lab/ml/monitoring/lab-cycle-3/summary/through=2026-06.json"))["data_origin"] == "SYNTHETIC_FIXTURE"
    again = mon.record_month(store, stream="lab-cycle-3", cycle=3, month="2026-06", forecast=forecast, actual_rows=actual_rows_for("2026-06", 1.0),
                             actual_published_at=(created + timedelta(minutes=9)).isoformat(), actual_run_id="run-june", data_origin="SYNTHETIC_FIXTURE")
    assert again["status"] == "ALREADY_RECORDED"                                                     # never rewritten
    assert json.loads(store.get("vercel-lab/ml/monitoring/lab-cycle-3/evaluations/2026-06.json"))["actual"]["shop"] == 100000.0
    late = mon.record_month(store, stream="lab-cycle-3", cycle=3, month="2026-07", forecast={**forecast, "forecast_run_id": "fc-none"}, actual_rows=actual_rows_for("2026-07"),
                            actual_published_at=T0.isoformat(), actual_run_id="run-july", data_origin="SYNTHETIC_FIXTURE")
    assert late["status"] == "EXCLUDED" and late["exclusion_reason"] == "NO_SHADOW"
    summary = json.loads(store.get("vercel-lab/ml/monitoring/lab-cycle-3/summary/through=2026-07.json"))
    assert summary["counted_months"] == 1 and [e["month"] for e in summary["excluded"]] == ["2026-07"]
    # published BEFORE the shadow existed (e.g. regenerated after the actual) -> excluded
    _r2, b2, store2, _o2 = real_shadow_store(tmp_path / "b", fid="fc-late")
    early = datetime.fromisoformat(b2["shadow"]["created_at"]) - timedelta(minutes=1)
    r = mon.record_month(store2, stream="s", cycle=1, month="2026-06", forecast=official_from(b2, "fc-late"), actual_rows=actual_rows_for("2026-06"),
                         actual_published_at=early.isoformat(), actual_run_id="x")
    assert r["exclusion_reason"] == "SHADOW_NOT_RECORDED_BEFORE_ACTUAL" and r["counted_months"] == 0


def test_streams_never_mix_and_the_same_month_is_counted_once_per_stream(tmp_path):
    """Two dataset cycles replaying the same months are separate streams; a month can never be double counted inside one stream."""
    _rows, b, store, _out = real_shadow_store(tmp_path)
    pub = (datetime.fromisoformat(b["shadow"]["created_at"]) + timedelta(minutes=1)).isoformat()
    kw = dict(month="2026-06", forecast=official_from(b, "fc-real"), actual_rows=actual_rows_for("2026-06"), actual_published_at=pub, actual_run_id="r")
    assert mon.record_month(store, stream="lab-cycle-1", cycle=1, **kw)["counted_months"] == 1
    assert mon.record_month(store, stream="lab-cycle-2", cycle=2, **kw)["counted_months"] == 1          # new cycle starts from its own evidence
    assert mon.record_month(store, stream="lab-cycle-1", cycle=2, **kw)["status"] == "ALREADY_RECORDED"  # same stream + month: no double count
    for st in ("lab-cycle-1", "lab-cycle-2"):
        assert json.loads(store.get(f"vercel-lab/ml/monitoring/{st}/summary/through=2026-06.json"))["counted_months"] == 1


def test_one_long_stream_accumulates_across_cycles_and_years(tmp_path):
    """An explicitly configured long-term stream keeps counting distinct months even when the cycle number changes and the year rolls over."""
    store = LocalDirStore(tmp_path)
    for k, (cycle, n_months) in enumerate(((1, 5), (2, 6), (3, 7))):                                   # data from Aug 2026: targets Jan, Feb, Mar 2027
        target_rows = make_rows(n_months, start="2026-08")
        target = mf.month_add("2026-08", n_months)
        b = tr.run_experiment(target_rows, target, kind="OFFICIAL_LINKED", source={**SRC, "source_run_id": f"r{k}"}, official_forecast_id=f"fc-{k}")
        tr.persist(store, b)
        pub = (datetime.fromisoformat(b["shadow"]["created_at"]) + timedelta(minutes=1)).isoformat()
        out = mon.record_month(store, stream="long", cycle=cycle, month=target, forecast=official_from(b, f"fc-{k}"), actual_rows=actual_rows_for(target), actual_published_at=pub, actual_run_id=f"a{k}")
        assert out["counted_months"] == k + 1
    last = json.loads(store.get("vercel-lab/ml/monitoring/long/summary/through=2027-03.json"))
    assert [m["month"] for m in last["monthly"]] == ["2027-01", "2027-02", "2027-03"] and last["evidence_level"] == "PRELIMINARY"
    assert {r["cycle"] for r in last["rows"]} == {1, 2, 3}


def test_monitoring_never_modifies_official_selection_or_forecast():
    rows = make_rows(5)
    core = [{"month": r["month"], "group": r["group"], "net_revenue": r["net_revenue"]} for r in rows]
    before = mf.generate_forecast(core, "2026-06", allow_ml=False)
    series([(8000, 6000)] * 6)
    assert mf.generate_forecast(core, "2026-06", allow_ml=False) == before


# ------------------------------------------------------------------ ML can never become Official automatically
def ml_winning_rows():
    """Synthetic series on which the ORIGINAL logic selects ML (strong cross-group trend that baselines lag behind)."""
    rows = []
    for i in range(9):
        month = mf.month_add("2026-01", i)
        for k, g in enumerate(G):
            net = 10000 + 2500 * i * (1 + 0.15 * k) + 400 * k
            rows.append({"month": month, "group": g, "net_revenue": net})
    return rows


def test_ml_is_never_selected_as_official_even_when_it_wins_walk_forward():
    rows = ml_winning_rows()
    original = mf.generate_forecast(rows, "2026-10")                                      # default = original behaviour (research/backtests)
    assert original["method_type"] == "ML" and original["validation"]["status"] == "OK", "fixture must make ML win under the original logic"
    official = mf.generate_forecast(rows, "2026-10", allow_ml=False)
    assert official["method_type"] == "BASELINE" and official["model_name"] in ("trailing_3_month_mean", "naive_previous_month")
    assert official["ml_passed_validation_blocked_by_policy"] is True and "human decision" in official["selection_reason"]
    assert official["validation"]["status"] == "OK"                                       # the validation is still computed and reported
    assert sorted(official["predictions"]) == G


def test_every_official_forecast_call_site_in_code_enforces_the_policy():
    import re
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in list((root / "api").glob("*.py")) + list((root / "pipeline").rglob("*.py")):
        if path.name == "monthly_forecast.py":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"generate_forecast\(", line) and "allow_ml=False" not in line and "unrestricted" not in line:
                offenders.append(f"{path.relative_to(root)}:{lineno}")
    assert not offenders, offenders
    worker = (root / "api" / "lab-worker.py").read_text(encoding="utf-8")
    assert 'result["method_type"] != "BASELINE"' in worker and "LAB_POLICY_ML_NOT_OFFICIAL" in worker      # runtime guard before anything is saved
    for forbidden in ("champion_approval", "approve_champion", "champion_ledger", "approver_id", "owner01", "switch_champion"):                                                    # scope: no approval workflow was added
        assert forbidden not in (root / "lib" / "lab-forecast.js").read_text(encoding="utf-8").lower()


def test_official_logic_records_what_the_original_logic_would_have_done_without_acting_on_it():
    rows = ml_winning_rows()
    shaped = [dict(r, gross_reference_sales=r["net_revenue"] * 1.1, ads_cost=r["net_revenue"] * 0.2, campaign_reduction=r["net_revenue"] * 0.05,
                   voucher_discount=r["net_revenue"] * 0.02, affiliate_cost=r["net_revenue"] * 0.06) for r in rows]
    b = tr.run_experiment(shaped, "2026-10", kind="OFFICIAL_LINKED", source=SRC, official_forecast_id="fc-x")
    logic = b["evaluation"]["official_logic_result"]
    assert logic["method_type"] == "BASELINE" and logic["ml_would_be_selected_without_policy"] is True


# ------------------------------------------------------------------ recovery (evaluation saved but summary missing / temporary failure + retry)
class FlakyStore(LocalDirStore):
    """Fails the next write whose key contains `fail_on` (simulates a crash/timeout between two object writes)."""
    fail_on = None

    def put(self, key, data):
        if self.fail_on and self.fail_on in key:
            self.fail_on = None
            raise OSError("injected storage failure")
        super().put(key, data)


def june_setup(tmp_path, store_cls=FlakyStore):
    rows = make_rows(5)
    b = tr.run_experiment(rows, "2026-06", kind="OFFICIAL_LINKED", source=SRC, official_forecast_id="fc-real")
    store = store_cls(tmp_path)
    tr.persist(store, b)
    published = (datetime.fromisoformat(b["shadow"]["created_at"]) + timedelta(minutes=5)).isoformat()
    return b, store, published


def test_evaluation_saved_but_summary_failed_is_repaired_from_the_stored_evidence_only(tmp_path):
    b, store, published = june_setup(tmp_path)
    forecast = official_from(b, "fc-real")
    kw = dict(stream="s", cycle=1, month="2026-06", forecast=forecast, actual_published_at=published, actual_run_id="run-june", data_origin="LOCAL_REAL_SOURCE_TEST")
    store.fail_on = "/summary/"
    with pytest.raises(OSError):
        mon.record_month(store, actual_rows=actual_rows_for("2026-06"), **kw)
    ev_path = "vercel-lab/ml/monitoring/s/evaluations/2026-06.json"
    assert store.exists(ev_path) and not store.exists("vercel-lab/ml/monitoring/s/summary/through=2026-06.json")
    evidence = store.get(ev_path)
    repaired = mon.record_month(store, actual_rows=[], **kw)                                  # retry does not need (or trust) a new actual
    assert repaired["status"] == "SUMMARY_REPAIRED" and repaired["counted_months"] == 1
    assert store.get(ev_path) == evidence                                                    # the evaluation was not rewritten
    assert mon.record_month(store, actual_rows=actual_rows_for("2026-06", 1.0), **kw)["status"] == "ALREADY_RECORDED"
    assert json.loads(store.get("vercel-lab/ml/monitoring/s/summary/through=2026-06.json"))["counted_months"] == 1


def test_temporary_failure_before_any_write_is_retried_with_the_original_publish_time(tmp_path):
    b, store, published = june_setup(tmp_path)
    forecast = official_from(b, "fc-real")
    loads = []

    def load(run_id):
        loads.append(run_id)
        return actual_rows_for("2026-06")
    store.fail_on = "/evaluations/"
    with pytest.raises(OSError):
        mon.record_month(store, stream="s", cycle=1, month="2026-06", forecast=forecast, actual_rows=actual_rows_for("2026-06"), actual_published_at=published,
                         actual_run_id="run-june", data_origin="LAB_RUNTIME")
    assert not store.exists("vercel-lab/ml/monitoring/s/evaluations/2026-06.json")
    pub = [{"month": "2026-06", "run_id": "run-june", "finished_at": published}]
    first = mon.repair_stream(store, stream="s", cycle=1, published=pub, forecasts={"2026-06": forecast}, load_actual_rows=load)
    assert first["evaluated"] == ["2026-06"] and loads == ["run-june"]
    row = json.loads(store.get("vercel-lab/ml/monitoring/s/evaluations/2026-06.json"))
    assert row["status"] == "EVALUATED" and row["actual_published_at"] == published               # honest time guard: original publish time, not the retry time
    again = mon.repair_stream(store, stream="s", cycle=1, published=pub, forecasts={"2026-06": forecast}, load_actual_rows=load)
    assert again["unchanged"] == ["2026-06"] and loads == ["run-june"]                          # second retry touches nothing and loads nothing
    assert json.loads(store.get("vercel-lab/ml/monitoring/s/summary/through=2026-06.json"))["counted_months"] == 1


def test_retry_never_creates_a_shadow_and_never_counts_a_late_one(tmp_path):
    rows = make_rows(5)
    store = FlakyStore(tmp_path)                                                                 # no shadow was ever recorded for this forecast
    forecast = {"forecast_run_id": "fc-none", "method_type": "BASELINE", "model_name": "trailing_3_month_mean", "results": {g: 20000.0 for g in G}}
    pub = [{"month": "2026-06", "run_id": "r", "finished_at": T0.isoformat()}]
    out = mon.repair_stream(store, stream="s", cycle=1, published=pub, forecasts={"2026-06": forecast}, load_actual_rows=lambda _r: actual_rows_for("2026-06"))
    assert out["evaluated"] == ["2026-06"]
    row = json.loads(store.get("vercel-lab/ml/monitoring/s/evaluations/2026-06.json"))
    assert row["status"] == "EXCLUDED" and row["exclusion_reason"] == "NO_SHADOW"
    assert not [k for k in store.list("vercel-lab/ml") if "shadow_forecast" in k]                # recovery wrote no shadow
    # a shadow recorded AFTER the actual was published (e.g. a regenerated draft) is not counted either
    b, store2, _p = june_setup(tmp_path / "late")
    early = (datetime.fromisoformat(b["shadow"]["created_at"]) - timedelta(minutes=1)).isoformat()
    out2 = mon.repair_stream(store2, stream="s", cycle=1, published=[{"month": "2026-06", "run_id": "r", "finished_at": early}], forecasts={"2026-06": official_from(b, "fc-real")},
                             load_actual_rows=lambda _r: actual_rows_for("2026-06"))
    assert json.loads(store2.get("vercel-lab/ml/monitoring/s/evaluations/2026-06.json"))["exclusion_reason"] == "SHADOW_NOT_RECORDED_BEFORE_ACTUAL"


def test_repair_skips_months_without_a_sealed_forecast_and_months_being_recorded_now(tmp_path):
    b, store, published = june_setup(tmp_path)
    pub = [{"month": "2026-06", "run_id": "a", "finished_at": published}, {"month": "2026-07", "run_id": "b", "finished_at": published}]
    out = mon.repair_stream(store, stream="s", cycle=1, published=pub, forecasts={"2026-06": official_from(b, "fc-real")}, load_actual_rows=lambda _r: actual_rows_for("2026-06"),
                            skip_months=("2026-06",))
    assert out["skipped"] == ["2026-06", "2026-07"] and out["evaluated"] == []
    assert not store.exists("vercel-lab/ml/monitoring/s/evaluations/2026-07.json")


# ------------------------------------------------------------------ data origin isolation
def test_origin_is_stored_in_every_evaluation_and_mismatching_origins_are_never_summed():
    rows = [mon.evaluate_month(month=m, forecast=sealed_forecast(m, 8000), shadow=shadow_for(m, "fc-" + m, 8000, 6000), actual_by_group={g: 20000.0 for g in G},
                               actual_published_at=(T0 + timedelta(days=1)).isoformat(), actual_run_id="r", data_origin=o)
            for m, o in zip(months(5), ("SYNTHETIC_FIXTURE", "LOCAL_REAL_SOURCE_TEST", "PRODUCTION", "PRODUCTION", "PRODUCTION"))]
    assert [r["data_origin"] for r in rows] == ["SYNTHETIC_FIXTURE", "LOCAL_REAL_SOURCE_TEST", "PRODUCTION", "PRODUCTION", "PRODUCTION"]
    prod = mon.summarize(rows, stream="s", data_origin="PRODUCTION")
    assert prod["counted_months"] == 3 and prod["evidence_level"] == "PRELIMINARY"               # only the three production rows
    assert sorted(e["month"] for e in prod["excluded"] if e["exclusion_reason"] == "DATA_ORIGIN_MISMATCH") == months(2)
    synth = mon.summarize(rows, stream="s", data_origin="SYNTHETIC_FIXTURE")
    assert synth["counted_months"] == 1 and synth["evidence_level"] == "INSUFFICIENT_EVIDENCE"
    assert all(r["data_origin"] == "PRODUCTION" for r in prod["rows"])
    legacy = {k: v for k, v in rows[2].items() if k != "data_origin"}
    assert mon.summarize([legacy], stream="s", data_origin="PRODUCTION")["counted_months"] == 0   # evidence with no recorded origin is not trusted


def test_a_stream_written_under_one_origin_does_not_absorb_a_later_run_of_another_origin(tmp_path):
    b, store, published = june_setup(tmp_path)
    forecast = official_from(b, "fc-real")
    mon.record_month(store, stream="s", cycle=1, month="2026-06", forecast=forecast, actual_rows=actual_rows_for("2026-06"), actual_published_at=published,
                     actual_run_id="r", data_origin="SYNTHETIC_FIXTURE")
    b2 = tr.run_experiment(make_rows(6), "2026-07", kind="OFFICIAL_LINKED", source={**SRC, "source_run_id": "r2"}, official_forecast_id="fc-july")
    tr.persist(store, b2)
    pub2 = (datetime.fromisoformat(b2["shadow"]["created_at"]) + timedelta(minutes=5)).isoformat()
    out = mon.record_month(store, stream="s", cycle=1, month="2026-07", forecast=official_from(b2, "fc-july"), actual_rows=actual_rows_for("2026-07"), actual_published_at=pub2,
                           actual_run_id="r2", data_origin="PRODUCTION")
    assert out["counted_months"] == 1                                                            # July counts alone under PRODUCTION; the synthetic June is shown as excluded
    summary = json.loads(store.get("vercel-lab/ml/monitoring/s/summary/through=2026-07.json"))
    assert summary["data_origin"] == "PRODUCTION" and [e["exclusion_reason"] for e in summary["excluded"]] == ["DATA_ORIGIN_MISMATCH"]


def test_late_repair_of_an_earlier_month_publishes_a_new_summary_revision_and_keeps_history(tmp_path):
    """Month 1 and 3 were evaluated, month 2 failed. After the repair the newest summary (a new revision) counts all three; the old file is untouched."""
    store = FlakyStore(tmp_path)
    forecasts, published, shadows = {}, [], {}
    for k, month in enumerate(("2026-06", "2026-07", "2026-08")):
        rows = make_rows(5 + k)
        b = tr.run_experiment(rows, month, kind="OFFICIAL_LINKED", source={**SRC, "source_run_id": f"r{k}"}, official_forecast_id=f"fc-{k}")
        tr.persist(store, b)
        forecasts[month] = official_from(b, f"fc-{k}")
        published.append({"month": month, "run_id": f"run-{k}", "finished_at": (datetime.fromisoformat(b["shadow"]["created_at"]) + timedelta(minutes=5)).isoformat()})
    for item in (published[0], published[2]):
        mon.record_month(store, stream="s", cycle=1, month=item["month"], forecast=forecasts[item["month"]], actual_rows=actual_rows_for(item["month"]),
                         actual_published_at=item["finished_at"], actual_run_id=item["run_id"])
    old_path = "vercel-lab/ml/monitoring/s/summary/through=2026-08.json"
    old_bytes = store.get(old_path)
    assert json.loads(old_bytes)["counted_months"] == 2
    out = mon.repair_stream(store, stream="s", cycle=1, published=published, forecasts=forecasts, load_actual_rows=lambda _r: actual_rows_for("2026-07"))
    assert out["evaluated"] == ["2026-07"] and out["latest_summary_through"] == "2026-08"
    assert store.get(old_path) == old_bytes                                                      # history is immutable
    newest = json.loads(store.get("vercel-lab/ml/monitoring/s/summary/through=2026-08.rev1.json"))
    assert newest["counted_months"] == 3 and [m["month"] for m in newest["monthly"]] == ["2026-06", "2026-07", "2026-08"]
    again = mon.repair_stream(store, stream="s", cycle=1, published=published, forecasts=forecasts, load_actual_rows=lambda _r: (_ for _ in ()).throw(AssertionError("must not load")))
    assert again["unchanged"] == ["2026-06", "2026-07", "2026-08"] and not store.exists("vercel-lab/ml/monitoring/s/summary/through=2026-08.rev2.json")
