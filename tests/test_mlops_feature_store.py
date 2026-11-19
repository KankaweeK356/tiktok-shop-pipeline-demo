"""Feature Store + Training Run contract (MADT8102 Ch.07). Synthetic rows are TEST FIXTURES only; real-data evidence is produced by the CLI."""
import copy

import pytest

from pipeline import monthly_forecast as mf
from pipeline.mlops import definitions as D
from pipeline.mlops import features as ft
from pipeline.mlops import training as tr
from pipeline.mlops.store import LocalDirStore, StoreError

G = D.GROUPS


def make_rows(n_months: int, *, start="2026-01"):
    rows = []
    for i in range(n_months):
        month = mf.month_add(start, i)
        for k, g in enumerate(G):
            net = 15000 + 900 * k + 650 * i + (320 if (i + k) % 3 == 0 else -210) + 40 * i * k
            gross = net * 1.09
            rows.append({"month": month, "group": g, "net_revenue": net, "gross_reference_sales": gross, "ads_cost": gross * (0.18 + 0.01 * k + 0.004 * i),
                         "campaign_reduction": gross * (0.06 + 0.002 * i), "voucher_discount": gross * 0.02, "affiliate_cost": gross * 0.06})
    return rows


SRC = {"source_run_id": "run-test", "warehouse_file_sha256": "abc", "published_through": "x"}


def test_feature_table_is_complete_versioned_and_labels_only_for_published_months():
    rows = make_rows(5)
    built = ft.build_feature_table(rows, "2026-06")
    table = built["table"]
    assert len(table) == 5 * len(G) and built["cutoff"] == "2026-05"
    defined = {f["name"] for f in D.FEATURES}
    assert {"lag1_group_net", "ads_to_gross_lag1", "campaign_discount_to_gross_lag1", "voucher_to_gross_lag1", "affiliate_to_gross_lag1", "net_trend_2m_pct"} <= defined
    assert all(f["used_in"] == [] for f in D.FEATURES if f["name"] in ("voucher_to_gross_lag1", "affiliate_to_gross_lag1"))   # defined for the future only
    infer = [r for r in table if r["is_inference"]]
    assert len(infer) == len(G) and all(r["label_net"] is None and r["origin_month"] == "2026-05" and r["label_month"] == "2026-06" for r in infer)
    assert all(r["label_net"] is not None for r in table if not r["is_inference"])
    assert all(r["known_at"] <= "2026-05-31" for r in table)


def test_point_in_time_features_never_use_later_months():
    rows = make_rows(6)
    base = ft.build_feature_table(rows, "2026-07")["table"]
    changed = copy.deepcopy(rows)
    for r in changed:                                            # corrupt everything from 2026-04 on: earlier origins must not notice
        if r["month"] >= "2026-04":
            r["net_revenue"] *= 7; r["ads_cost"] *= 5; r["campaign_reduction"] *= 9
    other = ft.build_feature_table(changed, "2026-07")["table"]
    feature_cols = [f["name"] for f in D.FEATURES]
    for a, b in zip(base, other):
        if a["origin_month"] < "2026-04":
            assert all(a[c] == b[c] for c in feature_cols), (a["origin_month"], a["group"])


def test_leakage_gap_and_unpublished_cutoff_are_refused():
    rows = make_rows(5)
    with pytest.raises(mf.ForecastError, match="FORECAST_LEAKAGE"):
        ft.build_feature_table(rows + make_rows(1, start="2026-06"), "2026-06")          # data of the target month itself
    with pytest.raises(mf.ForecastError, match="FORECAST_CUTOFF_NOT_PUBLISHED"):
        ft.build_feature_table(rows, "2026-07")
    gap = [r for r in rows if r["month"] != "2026-03"]
    with pytest.raises(mf.ForecastError, match="FORECAST_MONTH_GAP"):
        ft.build_feature_table(gap, "2026-06")


def test_forbidden_feature_names_are_rejected(monkeypatch):
    monkeypatch.setattr(ft, "FEATURES", [*D.FEATURES, {"name": "scenario_ads_plan", "type": "number"}])
    with pytest.raises(mf.ForecastError, match="FORECAST_FORBIDDEN_FEATURE"):
        ft.build_feature_table(make_rows(5), "2026-06")


def test_ridge_base_and_baselines_reproduce_the_official_logic_numbers_exactly():
    rows = make_rows(6)
    core = [{"month": r["month"], "group": r["group"], "net_revenue": r["net_revenue"]} for r in rows]
    official = mf.generate_forecast(core, "2026-07", allow_ml=False)       # the Official policy (ML is never selected)
    out = tr.run_experiment(rows, "2026-07", kind="EXPERIMENT_ONLY", source=SRC)
    ev = out["evaluation"]
    for key in ("shop_wape_pct", "shop_mae", "shop_bias"):
        assert ev["models_same_origins"]["ridge_base"][key] == pytest.approx(official["validation"]["ml"][key], abs=1e-6)
    for g in G:
        assert ev["models_same_origins"]["ridge_base"]["group_wape_pct"][g] == pytest.approx(official["validation"]["ml"]["group_wape_pct"][g], abs=1e-6)
    same = official["validation"]["baselines_same_origins_as_ml"]["trailing_3_month_mean"]
    assert ev["models_same_origins"]["baseline_trailing_3_month_mean"]["shop_wape_pct"] == pytest.approx(same["shop_wape_pct"], abs=1e-6)
    assert ev["official_logic_result"]["predictions"] == official["predictions"] and ev["official_logic_result"]["method_type"] == official["method_type"]
    if official["method_type"] == "BASELINE":
        assert ev["final_predictions"]["baseline_" + official["model_name"]]["predictions"] == official["predictions"]
    # official ML prediction equals ridge_base when ML is selected; otherwise the unchanged logic is simply recorded
    assert out["status"]["official_selection_changed"] is False and D.MODELS["ridge_marketing"]["official_candidate"] is False


def test_same_origins_for_every_model_and_eligibility_follows_the_unchanged_rule():
    five = tr.run_experiment(make_rows(5), "2026-06", kind="HISTORICAL_EVALUATION", source=SRC)["evaluation"]
    assert five["walk_forward"]["n_valid_origins"] == 2 and five["evaluation_status"] == "EXPERIMENTAL_INSUFFICIENT_VALIDATION"
    assert "prove nothing" in five["interpretation"]
    six = tr.run_experiment(make_rows(6), "2026-07", kind="EXPERIMENT_ONLY", source=SRC)["evaluation"]
    assert six["walk_forward"]["n_valid_origins"] == 3 and six["evaluation_status"] == "ELIGIBLE"
    for ev in (five, six):
        origins = {m["origins"] for m in ev["models_same_origins"].values()}
        assert origins == {ev["walk_forward"]["n_valid_origins"]}             # every model was scored on the very same origins


def test_missing_marketing_values_stop_only_that_model_and_are_never_zero_filled():
    rows = make_rows(6)
    for r in rows:
        if r["month"] == "2026-03":
            r["gross_reference_sales"] = 0.0                                  # ratios of that month become unknown
    out = tr.run_experiment(rows, "2026-07", kind="EXPERIMENT_ONLY", source=SRC)
    assert out["evaluation"]["models_same_origins"]["ridge_marketing"]["status"] == "NOT_RUN_MISSING_FEATURES"
    assert out["evaluation"]["models_same_origins"]["ridge_base"]["status"] == "OK"
    assert out["evaluation"]["final_predictions"]["ridge_marketing"]["predictions"] is None


def test_post_hoc_actual_is_only_used_for_evaluation():
    rows = make_rows(6)
    actual = {g: 9000.0 + 100 * i for i, g in enumerate(G)}
    with_actual = tr.run_experiment(rows[:5 * 5], "2026-06", kind="HISTORICAL_EVALUATION", source=SRC, actual_by_group=actual)
    without = tr.run_experiment(rows[:5 * 5], "2026-06", kind="HISTORICAL_EVALUATION", source=SRC)
    assert with_actual["evaluation"]["final_predictions"] == without["evaluation"]["final_predictions"]       # the actual never changes a prediction
    assert with_actual["evaluation"]["post_hoc_evaluation"]["label"].startswith("POST_HOC_EVALUATION")


def test_every_model_artifact_is_stored_even_when_ml_is_not_selected_and_nothing_is_overwritten(tmp_path):
    store = LocalDirStore(tmp_path)
    rows = make_rows(6)
    first = tr.persist(store, tr.run_experiment(rows, "2026-07", kind="EXPERIMENT_ONLY", source=SRC))
    keys_after_first = set(store.list("vercel-lab/ml"))
    base = first["run_path"]
    for name in D.MODELS:
        assert f"{base}/models/{name}.json" in keys_after_first
    for f in ("run.json", "evaluation.json", "params.json", "features_used.json", "status.json"):
        assert f"{base}/{f}" in keys_after_first
    assert any(k.endswith("features.parquet") for k in keys_after_first) and any(k.endswith("feature_definitions.json") for k in keys_after_first)
    second = tr.persist(store, tr.run_experiment(rows, "2026-07", kind="EXPERIMENT_ONLY", source=SRC))
    assert second["training_run_id"] != first["training_run_id"] and second["feature_set_state"] == "EXISTS_IDENTICAL"
    assert keys_after_first <= set(store.list("vercel-lab/ml"))                       # nothing removed
    changed = make_rows(6)
    changed[0]["net_revenue"] += 1.0
    with pytest.raises(StoreError, match="IMMUTABLE_FEATURE_SET_DIFFERS"):
        tr.persist(store, tr.run_experiment(changed, "2026-07", kind="EXPERIMENT_ONLY", source=SRC))


def test_running_an_experiment_does_not_change_the_official_forecast_function():
    rows = make_rows(6)
    core = [{"month": r["month"], "group": r["group"], "net_revenue": r["net_revenue"]} for r in rows]
    before = mf.generate_forecast(core, "2026-07")
    tr.run_experiment(rows, "2026-07", kind="EXPERIMENT_ONLY", source=SRC)
    assert mf.generate_forecast(core, "2026-07") == before


def test_s3_store_works_with_a_minimal_client_and_never_overwrites():
    import io
    from pipeline.mlops.store import S3Store, put_new

    class Minimal:                                               # only put_object/get_object, like the worker's test double
        def __init__(self): self.o = {}
        def put_object(self, Bucket, Key, Body, ContentType=None): self.o[(Bucket, Key)] = bytes(Body)
        def get_object(self, Bucket, Key): return {"Body": io.BytesIO(self.o[(Bucket, Key)])}

    store = S3Store(Minimal(), "b")
    assert store.exists("k") is False and put_new(store, "k", b"1") == "CREATED"
    assert put_new(store, "k", b"1") == "EXISTS_IDENTICAL"
    with pytest.raises(StoreError):
        put_new(store, "k", b"2")


# ------------------------------------------------------------------ comparison report + drift (steps 3-4)
from pipeline.mlops import drift as dr  # noqa: E402
from pipeline.mlops import report as rp  # noqa: E402


def bundle_for(n_months, **kw):
    rows = make_rows(n_months)
    target = mf.month_add(rows[-1]["month"], 1)
    return rows, tr.run_experiment(rows, target, kind="HISTORICAL_EVALUATION", source=SRC, **kw)


def test_report_states_levels_origins_selection_and_separates_validation_from_actual():
    rows, b = bundle_for(5)
    report = b["report"]
    assert "ระดับ Shop" in report["metric_level"]["shop"] and "Product Group" in report["metric_level"]["group"]
    dw = report["data_window"]
    assert dw["valid_origins"] == 2 and dw["min_origins_required"] == 3 and report["evaluation_status"] == "EXPERIMENTAL_INSUFFICIENT_VALIDATION"
    names = {m["model"]: m for m in report["validation"]["models"]}
    assert set(names) == set(D.MODELS) and all(m["origins"] == 2 for m in names.values())          # identical origins for every model
    assert names["ridge_marketing"]["role"] == "ML_EXPERIMENTAL" and names["baseline_trailing_3_month_mean"]["wape_vs_baseline_pp"] == 0
    assert report["official_selection"]["ridge_marketing_in_selection"] is False
    assert report["forecast_vs_actual"]["actual_shop"] is None                                       # no actual was supplied => nothing mixed in
    assert any("Insufficient" in x for x in report["limitations"])
    md = rp.render_markdown(report)
    assert "Validation" in md and "Forecast vs Actual" in md and "WAPE" in md


def test_report_post_hoc_actual_is_a_separate_section():
    rows = make_rows(6)
    target = "2026-07"
    actual = {g: 20000.0 + 100 * i for i, g in enumerate(G)}
    b = tr.run_experiment(rows[:25], "2026-06", kind="HISTORICAL_EVALUATION", source=SRC, actual_by_group={g: 20000.0 for g in G}, actual_source={"actual_run_id": "r"})
    fa = b["report"]["forecast_vs_actual"]
    assert fa["actual_shop"] == 100000.0 and set(fa["models"]) == set(D.MODELS)
    assert b["evaluation"]["post_hoc_evaluation"]["actual_source"] == {"actual_run_id": "r"}
    assert "actual_run_id" not in b["feature_meta"]["source"]                                         # the actual is never part of the feature set identity
    assert b["drift"]["performance_drift"]["status"] == "INSUFFICIENT_EVIDENCE" and b["drift"]["performance_drift"]["realised_months"] == 1


def test_drift_insufficient_evidence_instead_of_concluding_drift():
    rows = make_rows(4)                                                    # only 3 labelled origins < MIN_REFERENCE_ORIGINS
    b = tr.run_experiment(rows, "2026-05", kind="EXPERIMENT_ONLY", source=SRC)
    d = b["drift"]
    assert d["overall_status"] == "INSUFFICIENT_EVIDENCE" and d["recommendation"] == "COLLECT_MORE_DATA"
    assert d["input_drift"]["status"] == "INSUFFICIENT_EVIDENCE" and d["input_drift"]["features"] == {}
    assert d["auto_retrain"] is False and d["sealed_forecast_modified"] is False and d["mode"] == "ALERT_AND_RECOMMEND_ONLY"


def test_drift_alert_recommends_review_only_and_changes_nothing():
    rows = make_rows(6)
    shocked = [dict(r, ads_cost=r["ads_cost"] * 4) if r["month"] == "2026-06" else r for r in rows]    # last month's ad ratio jumps 4x
    target = "2026-07"
    before = mf.generate_forecast([{"month": r["month"], "group": r["group"], "net_revenue": r["net_revenue"]} for r in shocked], target)
    b = tr.run_experiment(shocked, target, kind="EXPERIMENT_ONLY", source=SRC)
    d = b["drift"]
    assert d["input_drift"]["features"]["ads_to_gross_lag1"]["status"] == "ALERT"
    assert d["overall_status"] == "ALERT" and d["recommendation"] == "RECOMMEND_RETRAIN_REVIEW" and d["auto_retrain"] is False
    after = mf.generate_forecast([{"month": r["month"], "group": r["group"], "net_revenue": r["net_revenue"]} for r in shocked], target)
    assert before["predictions"] == after["predictions"]                                           # monitoring never alters a forecast
    calm = tr.run_experiment(make_rows(6), target, kind="EXPERIMENT_ONLY", source=SRC)["drift"]
    assert calm["input_drift"]["features"]["ads_to_gross_lag1"]["status"] != "ALERT"


def test_performance_drift_needs_three_realised_months():
    rows = make_rows(6)
    two = dr.compute_drift(tr.ft.build_feature_table(rows, "2026-07")["table"], validation_wape_pct=8.0, realised=[{"month": "2026-05", "ape_pct": 30.0}, {"month": "2026-06", "ape_pct": 31.0}])
    assert two["performance_drift"]["status"] == "INSUFFICIENT_EVIDENCE"
    three = dr.compute_drift(tr.ft.build_feature_table(rows, "2026-07")["table"], validation_wape_pct=8.0, realised=[{"month": m, "ape_pct": 30.0} for m in ("2026-04", "2026-05", "2026-06")])
    assert three["performance_drift"]["status"] == "ALERT" and three["recommendation"] == "RECOMMEND_RETRAIN_REVIEW"


def test_report_and_drift_are_persisted_write_once(tmp_path):
    rows, b = bundle_for(5)
    store = LocalDirStore(tmp_path)
    out = tr.persist(store, b)
    for name in ("report", "drift"):
        assert store.exists(f"{out['run_path']}/{name}.json")
    with pytest.raises(StoreError):
        tr.put_new(store, f"{out['run_path']}/report.json", b"{}")


# ------------------------------------------------------------------ UI / API contracts (step 5)
from pathlib import Path  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]


def test_ml_panel_is_collapsible_read_only_and_has_no_hardcoded_results():
    app = (_ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
    block = app[app.index("// ---- ML Model & Experiment Details"):app.index("async function loadEvaluationView")]
    assert 'node("details", "dq-details fc-mlops")' in block and "det.open = ml.open" in block          # collapsible, closed by default
    for label in ("Official Forecast", "Historical Evaluation", "Experiment Only", "Published ER2", "Feature Store", "Model Selection", "Monitoring", "Decision"):
        assert label in block
    assert 'fcApi("mlops"' in block and 'fcApi("mlops_run"' in block
    assert '"seal"' not in block and "sealForecast" not in block and "seal_plan" not in block           # the panel can never seal or select
    import re
    assert not re.search(r"\b\d{2,3},\d{3}\.\d{2}\b", block) and not re.search(r"\b89967|104725|7\.43\b", block)   # no static result numbers


def test_mlops_read_api_never_writes_and_ticket_cannot_be_official():
    lib = (_ROOT / "lib" / "lab-mlops.js").read_text(encoding="utf-8")
    assert "PutObject" not in lib and "DeleteObject" not in lib and "sql" not in lib.lower().replace("lab-mlops", "")
    fc = (_ROOT / "lib" / "lab-forecast.js").read_text(encoding="utf-8")
    assert '["HISTORICAL_EVALUATION", "EXPERIMENT_ONLY"].includes(body.kind)' in fc
    worker = (_ROOT / "api" / "lab-worker.py").read_text(encoding="utf-8")
    seg = worker[worker.index("def run_mlops"):worker.index("class handler")]
    assert "save_draft_forecast" not in seg and "INSERT" not in seg.upper() and "UPDATE " not in seg.upper() and "DELETE" not in seg.upper()


def test_monitoring_block_is_inside_the_existing_panel_and_read_only():
    app = (_ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
    block = app[app.index("// ---- Champion vs Challenger Monitoring"):app.index("  function renderMlopsPanel()")]
    assert 'fcApi("monitoring")' in block and "renderMonitoringBlock" in app[app.index("function renderMlopsPanel"):]
    for label in ("Insufficient Evidence", "Preliminary", "Adequate", "Cumulative WAPE", "ผลรวมความคลาดเคลื่อนสะสม", "เดือนที่มีผลจริงสำหรับเปรียบเทียบ", "ไม่เปลี่ยน Champion และไม่สั่ง Retrain", "หลักการเปลี่ยน Champion"):
        assert label in block
    assert "MON_ORIGIN" in block and "SYNTHETIC_FIXTURE" in block and "LOCAL_REAL_SOURCE_TEST" in block                 # simulated / test evidence is labelled in the UI
    assert "ridge_marketing" not in block and "Ridge + Marketing" not in block                      # the experimental challenger is not a column here
    assert '"seal"' not in block and "mlops_run" not in block and "seal_plan" not in block and "generate" not in block
    assert 'fcApi("monitoring_repair"' in block and block.count('method: "POST"') == 2                      # the only writes: the repair ticket + its worker call (idempotent, evidence-only)
    import re
    assert not re.search(r"\b\d{1,3},\d{3}(\.\d+)?\b", block)                                      # no hard-coded results
    assert 'data-view="monitoring"' not in (_ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")   # no new main tab


def test_monitoring_is_also_on_the_forecast_vs_actual_page_without_a_new_tab():
    app = (_ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
    ev = app[app.index("function renderEvaluation()"):app.index("function setView(")]
    assert ev.count("renderEvalMonitoring()") == 2                                        # both the empty state and the normal state of the page
    section = app[app.index("function renderEvalMonitoring()"):app.index("function evalBars(")]
    assert "renderMonitoringBlock()" in section and 'node("details"' in section and "loadMonitoring(true)" in section
    assert 'data-view="monitoring"' not in (_ROOT / "dashboard" / "index.html").read_text(encoding="utf-8")


def test_forecast_page_shows_one_shadow_ml_line_marked_not_official():
    app = (_ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
    line = app[app.index("Shadow ML (Ridge) ทำนาย"):app.index("Shadow ML (Ridge) ทำนาย") + 700]
    assert "ไม่ใช่ Official" in line and "บันทึกก่อนรู้ยอดจริง" in line
    assert 'fcApi("mlops_shadow"' in app and "ยังไม่มี Shadow ML ที่ผูกกับ Forecast นี้" in app            # honest empty state for forecasts sealed before MLOps


def test_ml_panel_never_serves_cached_evidence_after_months_are_published():
    app = (_ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
    assert "{ loadMlops(state.fc.month, true); loadMonitoring(true); }" in app                  # forecast page reloads ML evidence every time it (re)loads while the panel is open
    assert "loadMlops(f.month, true); loadMonitoring(true);" in app                         # and every time the panel is opened
    assert "if (ml.evOpen !== false) loadMonitoring(true);" in app                          # and on the Forecast vs Actual page
    assert "a refresh keeps showing the old data" in app                                    # refresh does not blank the screen


def test_ml_panel_opens_by_itself_and_hides_the_optional_demo_buttons_until_asked():
    app = (_ROOT / "dashboard" / "app.js").read_text(encoding="utf-8")
    assert app.count('{ byMonth: {}, open: true, tab: "", busy: "", error: "" }') >= 3              # forecast page, forecast loader, evaluation page: open by default
    assert "det.open = ml.evOpen !== false" in app                                                  # evaluation section open by default as well
    assert 'const visible = ml.showExtras ? order : ["official_linked"]' in app                     # only the automatic tab is visible by default
    assert "ไม่ต้องกดปุ่มใดๆ" in app and "ระบบจะสร้างผล ML ให้เอง ไม่ต้องกดอะไรเพิ่ม" in app               # says plainly that nothing has to be pressed
