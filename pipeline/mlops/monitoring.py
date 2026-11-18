"""Champion-Challenger monitoring: Baseline (trailing 3 months) vs Ridge, one shadow forecast per sealed official forecast.

Counted months = months where BOTH models have a shadow forecast that was recorded (OFFICIAL_LINKED, bound to the sealed forecast id)
BEFORE the actual was published, and the actual of all 5 groups is available. Historical evaluations / experiments / backtests are never read here.
The recommendation only asks a human to review; it never switches the champion or retrains.
"""
from __future__ import annotations

from datetime import datetime

from .definitions import DEFAULT_PREFIX, GROUPS
from .store import StoreError, dumps, put_new

MONITORING_VERSION = "champion-challenger-1"
CHAMPION, CHALLENGER = "baseline_trailing_3_month_mean", "ridge_base"
LEVEL_PRELIMINARY, LEVEL_ADEQUATE = 3, 6
RULES = {"min_months": 6, "wape_gap_pp": 2.0, "wins_required": 4, "wins_window": 6, "group_tolerance_pp": 5.0}
EPS = 1e-9
MONTHS = [f"2026-{i:02d}" for i in range(6, 12)]       # forecast gate (June) .. last forecastable month


def _ts(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def evidence_level(n: int) -> str:
    return "ADEQUATE" if n >= LEVEL_ADEQUATE else "PRELIMINARY" if n >= LEVEL_PRELIMINARY else "INSUFFICIENT_EVIDENCE"


def _excluded(month, forecast, reason, detail, **extra):
    return {"month": month, "status": "EXCLUDED", "exclusion_reason": reason, "detail": detail,
            "official_forecast_id": forecast.get("forecast_run_id"), "official_method": forecast.get("method_type"), **extra}


def evaluate_month(*, month: str, forecast: dict, shadow: dict | None, actual_by_group: dict | None, actual_published_at, actual_run_id: str | None) -> dict:
    """One month. `forecast` = the sealed official forecast row; `shadow` = shadow_forecast.json found through the forecast id (or None)."""
    base = {"actual_run_id": actual_run_id, "actual_published_at": str(actual_published_at)}
    if shadow is None:
        return _excluded(month, forecast, "NO_SHADOW", "ไม่มี Shadow Forecast ที่บันทึกไว้คู่กับ Forecast นี้ (เช่น Seal ก่อนเปิดใช้ MLOps)", **base)
    if shadow.get("kind") != "OFFICIAL_LINKED" or shadow.get("official_forecast_id") != forecast.get("forecast_run_id"):
        return _excluded(month, forecast, "SHADOW_NOT_BOUND_TO_SEALED_FORECAST", "Shadow ไม่ได้ผูกกับ Forecast ID ที่ Seal จริง", **base)
    if shadow.get("target_month") != month:
        return _excluded(month, forecast, "SHADOW_TARGET_MISMATCH", "เดือนเป้าหมายของ Shadow ไม่ตรง", **base)
    if shadow.get("baseline") is None or shadow.get("ml") is None:
        return _excluded(month, forecast, "ML_OR_BASELINE_MISSING", "ต้องมีคำทำนายทั้ง Baseline และ ML จึงจะเทียบ (ไม่นับเดือนนี้ทั้งคู่)", **base)
    if actual_by_group is None or any(actual_by_group.get(g) is None for g in GROUPS):
        return _excluded(month, forecast, "ACTUAL_INCOMPLETE", "Actual ไม่ครบทั้ง 5 กลุ่มสินค้า", **base)
    try:
        before = _ts(shadow["created_at"]) < _ts(actual_published_at)
    except Exception:
        before = False
    if not before:
        return _excluded(month, forecast, "SHADOW_NOT_RECORDED_BEFORE_ACTUAL",
                         f"Shadow สร้างเมื่อ {shadow.get('created_at')} ไม่ก่อนเวลา Publish Actual {actual_published_at}", **base)
    prev = f"{int(month[:4]) - (month[5:] == '01')}-{(int(month[5:]) - 2) % 12 + 1:02d}"
    if shadow.get("cutoff_month") != prev:
        return _excluded(month, forecast, "CUTOFF_MISMATCH", "Data Cutoff ของ Shadow ไม่ใช่เดือนก่อนเดือนเป้าหมาย", **base)
    act = {g: float(actual_by_group[g]) for g in GROUPS}
    shop_act = sum(act.values())

    def side(s):
        err = {g: float(s["groups"][g]) - act[g] for g in GROUPS}                     # forecast - actual (positive = over-forecast)
        shop_err = float(s["shop"]) - shop_act
        return {"model": s["model"], "model_version": s["model_version"], "groups": {g: float(s["groups"][g]) for g in GROUPS}, "shop": float(s["shop"]),
                "shop_error": shop_err, "shop_abs_error": abs(shop_err), "shop_ape_pct": 100 * abs(shop_err) / shop_act if shop_act > 0 else None,
                "group_error": err, "group_abs_error": {g: abs(v) for g, v in err.items()}}
    return {"month": month, "status": "EVALUATED", "official_forecast_id": forecast.get("forecast_run_id"), "official_method": forecast.get("method_type"),
            "official_model": forecast.get("model_name"), "shadow_training_run_id": shadow.get("training_run_id"), "shadow_created_at": shadow["created_at"],
            "data_cutoff": shadow["data_cutoff"], "feature_version": shadow["feature_version"], **base,
            "actual": {"groups": act, "shop": shop_act}, "baseline": side(shadow["baseline"]), "ml": side(shadow["ml"])}


def summarize(rows: list[dict], *, cycle) -> dict:
    ev = sorted((r for r in rows if r["status"] == "EVALUATED"), key=lambda r: r["month"])
    excl = sorted((r for r in rows if r["status"] != "EVALUATED"), key=lambda r: r["month"])
    n = len(ev)

    def cum(key):
        act = sum(r["actual"]["shop"] for r in ev)
        err = sum(r[key]["shop_abs_error"] for r in ev)
        return {"wape_pct": 100 * err / act if act > 0 else None, "mae": err / n if n else None, "bias": sum(r[key]["shop_error"] for r in ev) / n if n else None,
                "abs_error_total": err}
    groups = {}
    for g in GROUPS:
        act = sum(r["actual"]["groups"][g] for r in ev)
        groups[g] = {k: (100 * sum(r[k]["group_abs_error"][g] for r in ev) / act if act > 0 else None) for k in ("baseline", "ml")}
        groups[g]["gap_pp"] = None if groups[g]["baseline"] is None else groups[g]["ml"] - groups[g]["baseline"]
    monthly, run_b, run_m = [], 0.0, 0.0
    for r in ev:
        run_b += r["baseline"]["shop_abs_error"]; run_m += r["ml"]["shop_abs_error"]
        monthly.append({"month": r["month"], "actual": r["actual"]["shop"], "baseline_forecast": r["baseline"]["shop"], "ml_forecast": r["ml"]["shop"],
                        "baseline_error": r["baseline"]["shop_error"], "ml_error": r["ml"]["shop_error"], "baseline_ape_pct": r["baseline"]["shop_ape_pct"],
                        "ml_ape_pct": r["ml"]["shop_ape_pct"], "cum_abs_error_baseline": run_b, "cum_abs_error_ml": run_m,
                        "ml_better": (r["ml"]["shop_ape_pct"] is not None and r["baseline"]["shop_ape_pct"] is not None and r["ml"]["shop_ape_pct"] < r["baseline"]["shop_ape_pct"])})
    cb, cm = (cum("baseline"), cum("ml")) if n else (None, None)
    level = evidence_level(n)
    rules = []
    if n:
        gap = cb["wape_pct"] - cm["wape_pct"]
        window = monthly[-RULES["wins_window"]:]
        wins = sum(1 for m in window if m["ml_better"])
        worst = max(groups.values(), key=lambda v: v["gap_pp"] if v["gap_pp"] is not None else -1e9)
        worse = [g for g, v in groups.items() if v["gap_pp"] is not None and v["gap_pp"] > RULES["group_tolerance_pp"] + EPS]
        rules = [
            {"rule": "EVIDENCE_ADEQUATE", "label": f"มีเดือนเปรียบเทียบจริงอย่างน้อย {RULES['min_months']} เดือน", "passed": n >= RULES["min_months"], "detail": f"{n} เดือน"},
            {"rule": "CUMULATIVE_WAPE_GAP", "label": f"Cumulative WAPE ของ ML ต่ำกว่า Baseline อย่างน้อย {RULES['wape_gap_pp']:g} จุด", "passed": gap >= RULES["wape_gap_pp"] - EPS,
             "detail": f"Baseline {cb['wape_pct']:.2f}% − ML {cm['wape_pct']:.2f}% = {gap:+.2f} จุด"},
            {"rule": "MONTHLY_WINS", "label": f"Monthly APE ของ ML ต่ำกว่า Baseline อย่างน้อย {RULES['wins_required']} จาก {RULES['wins_window']} เดือนล่าสุด",
             "passed": wins >= RULES["wins_required"], "detail": f"{wins} จาก {len(window)} เดือนล่าสุด"},
            {"rule": "GROUP_GUARDRAIL", "label": f"ไม่มี Product Group ใดที่ Cumulative WAPE ของ ML แย่กว่า Baseline เกิน {RULES['group_tolerance_pp']:g} จุด", "passed": not worse,
             "detail": ("ไม่มีกลุ่มเกินเกณฑ์" if not worse else "เกินเกณฑ์: " + ", ".join(f"{g} ({groups[g]['gap_pp']:+.2f} จุด)" for g in worse)) + f" · แย่สุด {max((v['gap_pp'] for v in groups.values() if v['gap_pp'] is not None), default=0):+.2f} จุด"}]
    if n < LEVEL_PRELIMINARY:
        status, msg = "INSUFFICIENT_EVIDENCE", f"มีเดือนเปรียบเทียบจริง {n} เดือน (ต้องอย่างน้อย {LEVEL_PRELIMINARY}) ยังไม่สรุปว่า ML ดีหรือแย่กว่า Baseline"
    elif n < LEVEL_ADEQUATE:
        status, msg = "PRELIMINARY_NOT_ASSESSED", f"ข้อมูลระดับ Preliminary ({n} เดือน) ตัวเลขใช้ดูแนวโน้มเท่านั้น ยังไม่ประเมินเกณฑ์พิจารณาเปลี่ยน Champion จนกว่าจะครบ {LEVEL_ADEQUATE} เดือน"
    elif all(r["passed"] for r in rules):
        status, msg = "RECOMMEND_REVIEW", "ผ่านทุกเงื่อนไข: แนะนำให้ผู้รับผิดชอบพิจารณาทบทวนการเปลี่ยน Champion จาก Baseline เป็น ML (ระบบไม่เปลี่ยนให้เอง)"
    else:
        status, msg = "NOT_RECOMMENDED", "ยังไม่ผ่านเกณฑ์: " + "; ".join(r["label"] for r in rules if not r["passed"])
    return {"monitoring_version": MONITORING_VERSION, "cycle": cycle, "through_month": ev[-1]["month"] if ev else None,
            "pair": {"champion": CHAMPION, "challenger": CHALLENGER, "note": "Ridge + Marketing อยู่ใน Experiment Only ไม่อยู่ในคู่เปรียบเทียบนี้"},
            "counted_months": n, "evidence_level": level, "levels": {"preliminary_from": LEVEL_PRELIMINARY, "adequate_from": LEVEL_ADEQUATE},
            "cumulative": {"baseline": cb, "ml": cm, "groups": groups}, "monthly": monthly, "rows": ev, "excluded": excl,
            "official_ml_months": [r["month"] for r in ev if r.get("official_method") == "ML"],
            "recommendation": {"status": status, "message": msg, "rules": rules, "rule_values": RULES, "human_decision_required": True,
                               "auto_switch_champion": False, "auto_retrain": False},
            "separation_note": "นับเฉพาะ Shadow Forecast ที่บันทึกก่อน Publish Actual · ไม่รวม Historical Evaluation, Experiment Only หรือ Backtest"}


def record_month(store, *, cycle, month: str, forecast: dict, actual_rows: list[dict], actual_published_at, actual_run_id: str | None,
                 prefix: str = DEFAULT_PREFIX) -> dict:
    """Called when the actual of `month` is published. Evaluates it, stores the evaluation write-once and a new immutable summary file."""
    base = f"{prefix}/monitoring/{cycle}"
    if store.exists(f"{base}/evaluations/{month}.json"):
        return {"status": "ALREADY_RECORDED", "month": month}                  # an evaluation is never recomputed or overwritten
    pointer_key = f"{prefix}/monitoring/by_forecast/{forecast['forecast_run_id']}.json"
    shadow = None
    if store.exists(pointer_key):
        import json
        pointer = json.loads(store.get(pointer_key))
        skey = f"{pointer['run_path']}/shadow_forecast.json"
        shadow = json.loads(store.get(skey)) if store.exists(skey) else None
    actual = {g: sum(float(r["net_revenue"]) for r in actual_rows if r["month"] == month and r["group"] == g) if any(r["month"] == month and r["group"] == g for r in actual_rows) else None
              for g in GROUPS}
    row = evaluate_month(month=month, forecast=forecast, shadow=shadow, actual_by_group=actual, actual_published_at=actual_published_at, actual_run_id=actual_run_id)
    state = put_new(store, f"{base}/evaluations/{month}.json", dumps(row))
    if state != "CREATED":
        return {"status": "ALREADY_RECORDED", "month": month}
    import json
    rows = []                                                                    # fixed keys per month: no bucket listing needed
    for m in MONTHS:
        key = f"{base}/evaluations/{m}.json"
        if store.exists(key):
            rows.append(json.loads(store.get(key)))
    summary = summarize(rows, cycle=cycle)
    put_new(store, f"{base}/summary/through={month}.json", dumps(summary))
    return {"status": row["status"], "exclusion_reason": row.get("exclusion_reason"), "month": month, "counted_months": summary["counted_months"],
            "evidence_level": summary["evidence_level"], "recommendation": summary["recommendation"]["status"]}
