"""Training runs: Baseline vs Ridge vs Ridge+Marketing on the SAME walk-forward origins, with every artifact kept.

Nothing here changes the official forecast: `official_logic_result` re-runs the unchanged `monthly_forecast.generate_forecast` on the same
rows only to record (and later prove) what the official selection logic decides. ridge_marketing is EXPERIMENTAL and never enters it.
"""
from __future__ import annotations

import subprocess
import time
import uuid
from datetime import datetime, timezone

import numpy as np

from .. import monthly_forecast as mf
from . import features as ft
from . import drift as drift_mod
from . import report as report_mod
from .definitions import DEFAULT_PREFIX, DUMMIES, FEATURE_VERSION, FEATURES, GROUPS, MODELS
from .store import StoreError, dumps, parquet_bytes, put_new, read_parquet

MIN_TRAIN_MONTHS, MIN_ORIGINS, ALPHA = 2, 3, 1.0          # identical to monthly_forecast.generate_forecast defaults
KINDS = ("HISTORICAL_EVALUATION", "OFFICIAL_LINKED", "EXPERIMENT_ONLY")


def _ridge_fit(X, y, alpha, n_num):
    """Same maths as monthly_forecast._ridge_fit, for any number of standardised numeric columns (n_num=3 reproduces it exactly)."""
    mean, std = X[:, :n_num].mean(axis=0), X[:, :n_num].std(axis=0)
    std[std == 0] = 1.0
    Z = np.hstack([(X[:, :n_num] - mean) / std, X[:, n_num:], np.ones((len(X), 1))])
    penalty = np.eye(Z.shape[1]) * alpha
    penalty[-1, -1] = 0.0
    return {"mean": mean, "std": std, "beta": np.linalg.solve(Z.T @ Z + penalty, Z.T @ y), "n_num": n_num}


def _ridge_predict(model, X):
    n = model["n_num"]
    Z = np.hstack([(X[:, :n] - model["mean"]) / model["std"], X[:, n:], np.ones((len(X), 1))])
    return np.maximum(Z @ model["beta"], 0.0)


def _matrix(rows, spec):
    cols = spec["numeric"] + spec["dummies"]
    if any(r[c] is None for r in rows for c in cols):
        return None                                       # missing feature values: the model is not run (never zero-filled)
    return np.array([[float(r[c]) for c in cols] for r in rows], dtype=float)


def _git_ref():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5).stdout.strip() or None
    except Exception:
        return None


def run_experiment(rows: list[dict], target_month: str, *, kind: str, source: dict, actual_by_group: dict | None = None,
                   alpha: float = ALPHA, min_train_months: int = MIN_TRAIN_MONTHS, min_origins: int = MIN_ORIGINS, official_forecast_id: str | None = None,
                   actual_source: dict | None = None) -> dict:
    """Build the feature table, train/evaluate every model on identical walk-forward origins and return all artifacts (not yet stored)."""
    if kind not in KINDS:
        raise ValueError("MLOPS_KIND_INVALID")
    started = time.time()
    built = ft.build_feature_table(rows, target_month)
    months, table = built["months"], built["table"]
    n = len(months)
    by_origin = {i: [r for r in table if r["origin_month"] == months[i]] for i in range(n)}
    net = {g: {m: float(next(r["net_revenue"] for r in rows if r["month"] == m and r["group"] == g)) for m in months} for g in GROUPS}
    series = net

    origins = [i for i in range(n - 1) if i >= min_train_months]            # origin i predicts months[i+1]; needs >= min_train_months of known labels
    models_run: dict[str, dict] = {}
    per_origin = []
    pairs = {name: [] for name in MODELS}
    for i in range(n - 1):
        actual = {g: series[g][months[i + 1]] for g in GROUPS}
        for bname, bkind in (("baseline_trailing_3_month_mean", "trailing_3_month_mean"), ("baseline_naive_previous_month", "naive_previous_month")):
            pred = mf._baseline_predict(bkind, series, months, i)
            pairs[bname].append((i, pred, actual))
        if i not in origins:
            continue
        for mname, spec in MODELS.items():
            if spec["kind"] != "ridge":
                continue
            train_rows = [r for j in range(i) for r in by_origin[j]]       # origins < i  =>  labels months[j+1] <= months[i]
            assert all(r["label_net"] is not None and r["label_month"] <= months[i] for r in train_rows)
            X, Xi = _matrix(train_rows, spec), _matrix(by_origin[i], spec)
            if X is None or Xi is None:
                pairs[mname].append((i, None, actual))
                continue
            y = np.array([r["label_net"] for r in train_rows], dtype=float)
            model = _ridge_fit(X, y, alpha, len(spec["numeric"]))
            pred = dict(zip([r["group"] for r in by_origin[i]], _ridge_predict(model, Xi).tolist()))
            pairs[mname].append((i, pred, actual))
    for i in origins:
        per_origin.append({"origin_month": months[i], "label_month": months[i + 1], "train_rows": i * len(GROUPS),
                           "actual_net_by_group": {g: round(series[g][months[i + 1]], 2) for g in GROUPS},
                           "predictions": {name: ({g: round(p[g], 2) for g in GROUPS} if p is not None else None)
                                           for name in MODELS for (oi, p, _a) in pairs[name] if oi == i}})

    def metrics_for(name, only_origins):
        sel = [(p, a) for (oi, p, a) in pairs[name] if oi in only_origins]
        if not sel or any(p is None for p, _ in sel):
            return {"origins": len(sel), "status": "NOT_RUN_MISSING_FEATURES" if sel else "NO_ORIGINS", "shop_wape_pct": None, "shop_mae": None, "shop_bias": None, "group_wape_pct": {}}
        return {**mf._metrics(sel), "status": "OK"}

    same = {name: metrics_for(name, set(origins)) for name in MODELS}                    # identical origins for every model
    baselines_all = {name: metrics_for(name, set(range(n - 1))) for name in MODELS if MODELS[name]["kind"] == "baseline"}
    eligible = len(origins) >= min_origins
    status = "ELIGIBLE" if eligible else "EXPERIMENTAL_INSUFFICIENT_VALIDATION"
    shop = {k: v["shop_wape_pct"] for k, v in same.items() if v.get("shop_wape_pct") is not None}
    ranking = sorted(shop, key=lambda k: shop[k]) if shop else []

    # final predictions for the target month: models are trained on every labelled row (origins < n-1), features of the cutoff month
    final = {}
    infer_rows = by_origin[n - 1]
    for bname, bkind in (("baseline_trailing_3_month_mean", "trailing_3_month_mean"), ("baseline_naive_previous_month", "naive_previous_month")):
        pred = mf._baseline_predict(bkind, series, months, n - 1)
        final[bname] = {"predictions": {g: round(max(pred[g], 0.0), 2) for g in GROUPS}, "artifact": {"kind": "baseline", "rule": bkind}}
    artifacts = {}
    for mname, spec in MODELS.items():
        if spec["kind"] != "ridge":
            artifacts[mname] = final[mname]["artifact"]
            continue
        train_rows = [r for j in range(n - 1) for r in by_origin[j]]
        X, Xi = _matrix(train_rows, spec), _matrix(infer_rows, spec)
        if X is None or Xi is None or not len(train_rows):
            final[mname] = {"predictions": None, "artifact": {"kind": "ridge", "status": "NOT_RUN_MISSING_FEATURES"}}
            artifacts[mname] = final[mname]["artifact"]
            continue
        y = np.array([r["label_net"] for r in train_rows], dtype=float)
        model = _ridge_fit(X, y, alpha, len(spec["numeric"]))
        preds = _ridge_predict(model, Xi)
        final[mname] = {"predictions": {r["group"]: round(float(p), 2) for r, p in zip(infer_rows, preds)}}
        artifacts[mname] = {"kind": "ridge", "model_name": mname, "alpha": alpha, "features": spec["numeric"] + spec["dummies"], "numeric_standardised": spec["numeric"],
                            "intercept_penalised": False, "beta": [round(float(b), 8) for b in model["beta"]], "mean": [round(float(v), 8) for v in model["mean"]],
                            "std": [round(float(v), 8) for v in model["std"]], "training_rows": int(len(y)), "trained_on_labels_through": months[-1],
                            "experimental": not spec.get("official_candidate", False)}
        final[mname]["artifact"] = artifacts[mname]
    for name in final:
        final[name]["shop_prediction"] = None if final[name]["predictions"] is None else round(sum(final[name]["predictions"].values()), 2)

    # what the UNCHANGED official logic decides on the same rows (recorded for comparison only)
    core = [{"month": r["month"], "group": r["group"], "net_revenue": r["net_revenue"]} for r in rows]
    official = mf.generate_forecast(core, target_month)
    official_logic = {"method_type": official["method_type"], "model_name": official["model_name"], "predictions": official["predictions"],
                      "shop_prediction": official["shop_prediction"], "selection_reason": official["selection_reason"],
                      "validation_status": official["validation"]["status"], "ml_origins": len(official["validation"]["ml_origins"]),
                      "note": "Output of the unchanged monthly_forecast.generate_forecast on the same rows. Not produced by this run."}

    post_hoc = None
    if actual_by_group is not None:
        act = {g: float(actual_by_group[g]) for g in GROUPS}
        post_hoc = {"label": "POST_HOC_EVALUATION (the target month was already published; used only for evaluation, never as a feature)",
                    "actual_net_by_group": {g: round(act[g], 2) for g in GROUPS}, "actual_shop": round(sum(act.values()), 2), "models": {},
                    "actual_source": actual_source or {}}                  # evidence of where the post-hoc actual came from; never part of the feature set
        for name, f in final.items():
            if f["predictions"] is None:
                post_hoc["models"][name] = None
                continue
            err = {g: round(act[g] - f["predictions"][g], 2) for g in GROUPS}
            post_hoc["models"][name] = {"shop_prediction": f["shop_prediction"], "shop_error_actual_minus_forecast": round(sum(act.values()) - f["shop_prediction"], 2),
                                        "shop_ape_pct": round(100 * abs(sum(act.values()) - f["shop_prediction"]) / sum(act.values()), 4) if sum(act.values()) > 0 else None,
                                        "group_error": err}
    run_id = str(uuid.uuid4())
    manifest_rows = [{k: v for k, v in r.items()} for r in table]
    f_stats = ft.feature_stats(table)
    feature_meta = {"feature_version": FEATURE_VERSION, "target_month": target_month, "cutoff_month": built["cutoff"], "months": months, "rows": len(table),
                    "origins": n, "labelled_rows": sum(1 for r in table if not r["is_inference"]), "inference_rows": sum(1 for r in table if r["is_inference"]),
                    "source": source, "input_sha256": ft.input_hash(rows), "feature_stats": f_stats,
                    "point_in_time": {"rule": "features of row (origin, group) use months <= origin only; label = next month; inference row = cutoff month",
                                      "max_known_at": max(r["known_at"] for r in table), "no_future_rows": all(r["origin_month"] <= built["cutoff"] for r in table)}}
    run = {"training_run_id": run_id, "kind": kind, "created_at": datetime.now(timezone.utc).isoformat(), "target_month": target_month, "cutoff_month": built["cutoff"],
           "data_months": months, "evaluation_status": status, "origins_used": len(origins), "min_origins_required": min_origins,
           "official_forecast_link": {"official_forecast_id": official_forecast_id, "role": "REFERENCE_ONLY" if kind != "OFFICIAL_LINKED" else "EVIDENCE_FOR_OFFICIAL_FORECAST",
                                     "note": "A training run never creates or changes a sealed forecast"},
           "feature_set": {"feature_version": FEATURE_VERSION, "source": source}, "code_ref": _git_ref(), "duration_seconds": round(time.time() - started, 3)}
    evaluation = {"training_run_id": run_id, "evaluation_status": status, "walk_forward": {"origins": [months[i] for i in origins], "n_valid_origins": len(origins),
                  "min_origins_required": min_origins, "min_train_months": min_train_months, "identical_origins_for_all_models": True},
                  "models_same_origins": same, "baselines_all_origins": baselines_all, "per_origin": per_origin, "ranking_by_shop_wape": ranking,
                  "interpretation": ("Insufficient validation: fewer than the minimum walk-forward origins. Results are experimental and prove nothing about model quality."
                                     if not eligible else "Eligible: enough walk-forward origins. Ranking is descriptive; official selection remains the unchanged logic."),
                  "final_predictions": final, "official_logic_result": official_logic, "post_hoc_evaluation": post_hoc}
    params = {"alpha": alpha, "min_train_months": min_train_months, "min_origins": min_origins, "standardise": "numeric columns only", "intercept_penalised": False,
              "models": {k: {kk: vv for kk, vv in v.items() if kk != "description"} for k, v in MODELS.items()}}
    realised = []
    if post_hoc:
        key = "ridge_base" if official_logic["method_type"] == "ML" else "baseline_" + official_logic["model_name"]
        obs = post_hoc["models"].get(key)
        if obs:
            realised.append({"month": target_month, "model": key, "ape_pct": obs["shop_ape_pct"]})
    drift = drift_mod.compute_drift(manifest_rows, validation_wape_pct=same["baseline_trailing_3_month_mean"].get("shop_wape_pct"), realised=realised)
    bundle_core = {"run": run, "evaluation": evaluation, "feature_meta": feature_meta}
    report = report_mod.build_report(bundle_core)
    return {"run": run, "evaluation": evaluation, "params": params, "artifacts": artifacts, "feature_meta": feature_meta, "feature_rows": manifest_rows,
            "drift": drift, "report": report,
            "features_used": {k: ({"numeric": v.get("numeric"), "dummies": v.get("dummies")} if v["kind"] == "ridge" else {"features": []}) for k, v in MODELS.items()},
            "status": {"state": "SUCCEEDED", "official_selection_changed": False}}


def persist(store, bundle: dict, *, prefix: str = DEFAULT_PREFIX) -> dict:
    """Write feature set (idempotent, write-once) and training run (new id => new path). Nothing existing is overwritten."""
    run, fm = bundle["run"], bundle["feature_meta"]
    src = fm["source"]
    fkey = f"{prefix}/features/{FEATURE_VERSION}/{src.get('source_run_id') or 'unknown'}/target={fm['target_month']}"
    rows_now = bundle["feature_rows"]
    if store.exists(f"{fkey}/features.parquet"):
        if read_parquet(store.get(f"{fkey}/features.parquet")) != rows_now:
            raise StoreError(f"IMMUTABLE_FEATURE_SET_DIFFERS: {fkey}")
        fstate = "EXISTS_IDENTICAL"
    else:
        store.put(f"{fkey}/features.parquet", parquet_bytes(rows_now))
        fstate = "CREATED"
    put_new(store, f"{fkey}/feature_definitions.json", dumps({"feature_version": FEATURE_VERSION, "features": FEATURES}))
    put_new(store, f"{fkey}/manifest.json", dumps({k: v for k, v in fm.items()}))
    rkey = f"{prefix}/runs/{run['training_run_id']}"
    paths = {"run": f"{rkey}/run.json", "evaluation": f"{rkey}/evaluation.json", "params": f"{rkey}/params.json", "features_used": f"{rkey}/features_used.json", "status": f"{rkey}/status.json",
             "report": f"{rkey}/report.json", "drift": f"{rkey}/drift.json"}
    run = {**run, "feature_set_path": fkey, "artifacts": {name: f"{rkey}/models/{name}.json" for name in bundle["artifacts"]}}
    for name, key in (("run", paths["run"]), ("evaluation", paths["evaluation"]), ("params", paths["params"]), ("features_used", paths["features_used"]), ("status", paths["status"]),
                      ("report", paths["report"]), ("drift", paths["drift"])):
        put_new(store, key, dumps(run if name == "run" else bundle[name] if name in bundle else bundle["status"]))
    for name, art in bundle["artifacts"].items():
        put_new(store, f"{rkey}/models/{name}.json", dumps(art))
    put_new(store, f"{prefix}/index/{run['kind']}/{fm['target_month']}/{run['training_run_id']}.json",
            dumps({"training_run_id": run["training_run_id"], "kind": run["kind"], "target_month": fm["target_month"], "evaluation_status": run["evaluation_status"],
                   "created_at": run["created_at"], "run_path": rkey}))
    return {"training_run_id": run["training_run_id"], "run_path": rkey, "feature_set_path": fkey, "feature_set_state": fstate, "evaluation_status": run["evaluation_status"]}
