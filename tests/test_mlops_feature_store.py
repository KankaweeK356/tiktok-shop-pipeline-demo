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
    official = mf.generate_forecast(core, "2026-07")
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
