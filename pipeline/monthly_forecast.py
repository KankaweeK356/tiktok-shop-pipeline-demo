"""Next-month Net Revenue forecast per Product Group (PG01..PG05) from PUBLISHED ER2 only.

Honest by construction:

* inputs are the monthly group Net Revenue of months <= the cutoff month; a row dated after the
  cutoff raises `FORECAST_LEAKAGE` (nothing from the target month can reach features or selection);
* a naive baseline (previous month) and a trailing-3-month mean are always evaluated;
* the ML challenger (pooled ridge regression, closed form) is only *eligible* when at least
  `min_origins` expanding-window walk-forward origins exist; otherwise the official method is the
  best BASELINE and the result says so (`INSUFFICIENT_VALIDATION`);
* ML is chosen only when it beats the best baseline on exactly the same origins (shop WAPE) without
  a material group-level regression. Nothing here is a fixed score, winner or hardcoded value.
"""
from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np

GROUPS = ("PG01", "PG02", "PG03", "PG04", "PG05")
FEATURE_VERSION = "mf-features-1"
ML_VERSION = "ridge-pooled-1"
FORBIDDEN_FEATURE_TOKENS = ("scenario_design", "expected", "qa_", "target_month_actual", "golden")
FEATURE_NAMES = ("lag1_group_net", "trailing3_group_net_mean", "days_in_label_month", *[f"group_{g}" for g in GROUPS])


class ForecastError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


def month_add(month: str, delta: int) -> str:
    year, number = int(month[:4]), int(month[5:7])
    index = year * 12 + (number - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def days_in(month: str) -> int:
    return calendar.monthrange(int(month[:4]), int(month[5:7]))[1]


def read_published_group_months(er2_path: Path) -> list[dict]:
    """Monthly Net Revenue per group from the Published ER2 daily mart (grain: month x group)."""
    import duckdb
    with duckdb.connect(str(er2_path), read_only=True) as db:
        rows = db.execute("""
            SELECT d.Year_Month, m.Product_Group_ID, SUM(m.Net_Revenue)
              FROM Mart_Product_Group_Daily_Performance m
              JOIN Dim_Date d ON d.Date_Key = m.Date_Key
             GROUP BY 1, 2 ORDER BY 1, 2""").fetchall()
    return [{"month": r[0], "group": r[1], "net_revenue": float(r[2])} for r in rows]


def _series(rows: list[dict]) -> tuple[list[str], dict[str, dict[str, float]]]:
    months = sorted({r["month"] for r in rows})
    series = {g: {m: 0.0 for m in months} for g in GROUPS}
    for r in rows:
        if r["group"] not in series:
            raise ForecastError("FORECAST_UNKNOWN_GROUP", r["group"])
        series[r["group"]][r["month"]] += float(r["net_revenue"])
    return months, series


def _features(series: dict[str, dict[str, float]], months: list[str], upto: int, group: str, label_month: str) -> list[float]:
    """Features known at the end of months[upto] (inclusive) for the label month."""
    history = [series[group][m] for m in months[: upto + 1]]
    lag1 = history[-1]
    trail = float(np.mean(history[-3:]))
    return [lag1, trail, float(days_in(label_month)), *[1.0 if g == group else 0.0 for g in GROUPS]]


def _ridge_fit(X: np.ndarray, y: np.ndarray, alpha: float):
    mean, std = X[:, :3].mean(axis=0), X[:, :3].std(axis=0)
    std[std == 0] = 1.0
    Z = np.hstack([(X[:, :3] - mean) / std, X[:, 3:], np.ones((len(X), 1))])
    penalty = np.eye(Z.shape[1]) * alpha
    penalty[-1, -1] = 0.0                                   # intercept is not penalised
    beta = np.linalg.solve(Z.T @ Z + penalty, Z.T @ y)
    return {"mean": mean, "std": std, "beta": beta}


def _ridge_predict(model, X: np.ndarray) -> np.ndarray:
    Z = np.hstack([(X[:, :3] - model["mean"]) / model["std"], X[:, 3:], np.ones((len(X), 1))])
    return np.maximum(Z @ model["beta"], 0.0)


def _train_rows(series, months, last_label_index: int):
    X, y = [], []
    for j in range(0, last_label_index):                    # features at j, label months[j+1] <= months[last_label_index]
        for g in GROUPS:
            X.append(_features(series, months, j, g, months[j + 1]))
            y.append(series[g][months[j + 1]])
    return np.array(X, dtype=float), np.array(y, dtype=float)


def _baseline_predict(kind: str, series, months, upto: int) -> dict[str, float]:
    out = {}
    for g in GROUPS:
        history = [series[g][m] for m in months[: upto + 1]]
        out[g] = history[-1] if kind == "naive_previous_month" else float(np.mean(history[-3:]))
    return out


def _metrics(pairs: list[tuple[dict, dict]]) -> dict:
    """pairs = [(predicted_by_group, actual_by_group)] for the same origins."""
    if not pairs:
        return {"origins": 0, "shop_wape_pct": None, "shop_mae": None, "shop_bias": None, "group_wape_pct": {}}
    shop_err = [sum(p.values()) - sum(a.values()) for p, a in pairs]
    shop_act = sum(sum(a.values()) for _, a in pairs)
    group_wape = {}
    for g in GROUPS:
        act = sum(a[g] for _, a in pairs)
        err = sum(abs(p[g] - a[g]) for p, a in pairs)
        group_wape[g] = round(100.0 * err / act, 4) if act > 0 else None
    return {"origins": len(pairs),
            "shop_wape_pct": round(100.0 * sum(abs(e) for e in shop_err) / shop_act, 4) if shop_act > 0 else None,
            "shop_mae": round(sum(abs(e) for e in shop_err) / len(shop_err), 2),
            "shop_bias": round(sum(shop_err) / len(shop_err), 2),       # forecast - actual
            "group_wape_pct": group_wape}


def generate_forecast(rows: list[dict], target_month: str, *, min_train_months: int = 2, min_origins: int = 3,
                      alpha: float = 1.0, group_degradation_tolerance_pp: float = 5.0,
                      improvement_margin_pp: float = 0.0, allow_ml: bool = True) -> dict:
    """Forecast `target_month` using only `rows` (monthly group Net Revenue <= cutoff).

    allow_ml=False is the project policy for the OFFICIAL forecast: ML may be validated and reported but is never selected here; changing the
    champion to ML is a decision made outside this system. The default (True) keeps the original behaviour for research/backtests."""
    if not rows:
        raise ForecastError("FORECAST_NO_PUBLISHED_DATA")
    cutoff = month_add(target_month, -1)
    months, series = _series(rows)
    if months[-1] > cutoff:
        raise ForecastError("FORECAST_LEAKAGE", f"data for {months[-1]} is later than cutoff {cutoff}")
    if months[-1] != cutoff:
        raise ForecastError("FORECAST_CUTOFF_NOT_PUBLISHED", f"published through {months[-1]}, need {cutoff}")
    expected = [month_add(months[0], i) for i in range(len(months))]
    if months != expected:
        raise ForecastError("FORECAST_MONTH_GAP", f"published months are not contiguous: {months}")
    present = {(r["month"], r["group"]) for r in rows}
    missing = [(m, g) for m in months for g in GROUPS if (m, g) not in present]
    if missing:                                                    # a missing group-month must never be silently treated as zero revenue
        raise ForecastError("FORECAST_INCOMPLETE_GROUP_MONTHS", f"every published month needs all five groups; missing {missing[:5]}")
    for name in FEATURE_NAMES:
        if any(token in name for token in FORBIDDEN_FEATURE_TOKENS):
            raise ForecastError("FORECAST_FORBIDDEN_FEATURE", name)
    n = len(months)
    last = n - 1

    # ---- walk-forward evaluation on identical origins -------------------------------
    baseline_pairs = {"naive_previous_month": [], "trailing_3_month_mean": []}
    ml_pairs: list[tuple[dict, dict]] = []
    origins = []
    for i in range(0, n - 1):                                   # origin i predicts months[i+1]
        actual = {g: series[g][months[i + 1]] for g in GROUPS}
        for kind in baseline_pairs:
            baseline_pairs[kind].append((_baseline_predict(kind, series, months, i), actual))
        if i >= min_train_months:                              # >= min_train_months of known labels
            X, y = _train_rows(series, months, i)
            model = _ridge_fit(X, y, alpha)
            feats = np.array([_features(series, months, i, g, months[i + 1]) for g in GROUPS])
            predicted = dict(zip(GROUPS, _ridge_predict(model, feats).tolist()))
            ml_pairs.append((predicted, actual))
            origins.append({"origin_month": months[i], "label_month": months[i + 1]})
    # baselines are compared on the very same origins as the challenger when it exists
    eval_from = len(baseline_pairs["naive_previous_month"]) - len(ml_pairs)
    same_origin = {k: v[eval_from:] for k, v in baseline_pairs.items()}
    base_metrics_all = {k: _metrics(v) for k, v in baseline_pairs.items()}
    base_metrics_same = {k: _metrics(v) for k, v in same_origin.items()}
    ml_metrics = _metrics(ml_pairs)

    # ---- best baseline ----------------------------------------------------------------
    def wape(m):
        return m["shop_wape_pct"] if m["shop_wape_pct"] is not None else float("inf")
    best_baseline = min(base_metrics_all, key=lambda k: (wape(base_metrics_all[k]), k != "naive_previous_month"))
    if n < 2:
        best_baseline = "naive_previous_month"

    # ---- selection ----------------------------------------------------------------------
    notes, method, model_name = [], "BASELINE", best_baseline
    selection = ""
    ml_passed_but_blocked = False
    if len(ml_pairs) < min_origins:
        selection = (f"INSUFFICIENT_VALIDATION: only {len(ml_pairs)} valid walk-forward origin(s) for the ML challenger "
                     f"(need {min_origins}); official forecast uses BASELINE {best_baseline}")
        notes.append("ML challenger was not eligible; no ML accuracy is claimed.")
    else:
        compare = base_metrics_same[min(base_metrics_same, key=lambda k: wape(base_metrics_same[k]))]
        best_same = min(base_metrics_same, key=lambda k: wape(base_metrics_same[k]))
        beats_shop = (ml_metrics["shop_wape_pct"] is not None and compare["shop_wape_pct"] is not None and
                      ml_metrics["shop_wape_pct"] < compare["shop_wape_pct"] - improvement_margin_pp)
        group_ok = all(
            ml_metrics["group_wape_pct"][g] is None or compare["group_wape_pct"][g] is None or
            ml_metrics["group_wape_pct"][g] <= compare["group_wape_pct"][g] + group_degradation_tolerance_pp
            for g in GROUPS)
        if beats_shop and group_ok and not allow_ml:
            ml_passed_but_blocked = True
            best_baseline = best_same
            model_name = best_same
            selection = (f"BASELINE {best_same} selected by policy: ML challenger passed walk-forward (shop WAPE {ml_metrics['shop_wape_pct']}% < "
                         f"{compare['shop_wape_pct']}% on {len(ml_pairs)} origins) but ML cannot become the Official model automatically; "
                         f"champion change is a human decision outside this system")
            notes.append("ML passed walk-forward validation but is not eligible to be Official under the project policy.")
        elif beats_shop and group_ok:
            method, model_name = "ML", "ridge_pooled_group_month"
            selection = (f"ML selected: shop WAPE {ml_metrics['shop_wape_pct']}% < best baseline ({best_same}) "
                         f"{compare['shop_wape_pct']}% on the same {len(ml_pairs)} walk-forward origins; "
                         f"no group regressed more than {group_degradation_tolerance_pp} pp")
        else:
            best_baseline = best_same
            model_name = best_same
            why = "does not beat" if not beats_shop else "regresses a group beyond tolerance against"
            selection = (f"BASELINE {best_same} selected: ML challenger {why} the baseline on the same "
                         f"{len(ml_pairs)} origins (ML shop WAPE {ml_metrics['shop_wape_pct']}% vs {compare['shop_wape_pct']}%)")
    # ---- final prediction ---------------------------------------------------------------
    if method == "ML":
        X, y = _train_rows(series, months, last)
        model = _ridge_fit(X, y, alpha)
        feats = np.array([_features(series, months, last, g, target_month) for g in GROUPS])
        preds = dict(zip(GROUPS, _ridge_predict(model, feats).tolist()))
        coefficients = {"features": list(FEATURE_NAMES) + ["intercept"], "beta": [round(float(b), 6) for b in model["beta"]],
                        "mean": [round(float(v), 6) for v in model["mean"]], "std": [round(float(v), 6) for v in model["std"]],
                        "alpha": alpha, "training_rows": int(len(y))}
    else:
        preds = _baseline_predict(model_name, series, months, last)
        coefficients = None
    predictions = {g: round(max(float(preds[g]), 0.0), 2) for g in GROUPS}
    canonical = json.dumps([[r["month"], r["group"], round(float(r["net_revenue"]), 2)] for r in sorted(rows, key=lambda r: (r["month"], r["group"]))])
    input_hash = hashlib.sha256(canonical.encode()).hexdigest()
    cutoff_date = date(int(cutoff[:4]), int(cutoff[5:7]), days_in(cutoff))
    return {
        "target_month": target_month, "training_cutoff_date": cutoff_date.isoformat(), "published_through": months[-1],
        "method_type": method, "model_name": model_name,
        "model_version": ML_VERSION if method == "ML" else "baseline-1", "feature_version": FEATURE_VERSION,
        "predictions": predictions, "shop_prediction": round(sum(predictions.values()), 2),
        "selection_reason": selection, "ml_passed_validation_blocked_by_policy": ml_passed_but_blocked, "validation_notes": " | ".join(notes) or None,
        "baseline_validation_wape_pct": (base_metrics_same if len(ml_pairs) else base_metrics_all)[best_baseline]["shop_wape_pct"],
        "model_validation_wape_pct": ml_metrics["shop_wape_pct"] if len(ml_pairs) >= min_origins else None,
        "validation": {"min_origins_required": min_origins, "ml_origins": origins, "ml": ml_metrics,
                       "baselines_all_origins": base_metrics_all, "baselines_same_origins_as_ml": base_metrics_same,
                       "status": "OK" if len(ml_pairs) >= min_origins else "INSUFFICIENT_VALIDATION"},
        "source_snapshot_sha256": input_hash, "months_used": months,
        "model_manifest": {"feature_version": FEATURE_VERSION, "features": list(FEATURE_NAMES), "model": coefficients,
                           "input_sha256": input_hash},
    }
