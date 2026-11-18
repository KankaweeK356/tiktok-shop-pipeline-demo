"""Champion-Challenger monitoring: the OFFICIAL baseline of each month (best of trailing-3 / naive, as sealed) vs Ridge, one shadow forecast per sealed forecast.

Counted months = months where BOTH models have a shadow forecast that was recorded (OFFICIAL_LINKED, bound to the sealed forecast id)
BEFORE the actual was published, and the actual of all 5 groups is available. Historical evaluations / experiments / backtests are never read here.
The recommendation only asks a human to review; it never switches the champion or retrains.
"""
from __future__ import annotations

from datetime import datetime

from .definitions import DEFAULT_PREFIX, GROUPS
from .store import StoreError, dumps, put_new

MONITORING_VERSION = "champion-challenger-1"
CHALLENGER = "ridge_base"
ORIGINS = ("SYNTHETIC_FIXTURE", "LOCAL_REAL_SOURCE_TEST", "LAB_RUNTIME", "PRODUCTION")   # where the evidence came from (never mixed in one stream)
LEVEL_PRELIMINARY, LEVEL_ADEQUATE = 3, 6
RULES = {"min_months": 6, "wape_gap_pp": 2.0, "wins_required": 4, "wins_window": 6, "group_tolerance_pp": 5.0}
EPS = 1e-9
WINDOW_MONTHS = 36           # evaluation files looked up per summary (rolling window; no calendar range is hard-coded)


def month_add(month: str, delta: int) -> str:
    y, m = int(month[:4]), int(month[5:7]) - 1 + delta
    return f"{y + m // 12}-{m % 12 + 1:02d}"


def _ts(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def evidence_level(n: int) -> str:
    return "ADEQUATE" if n >= LEVEL_ADEQUATE else "PRELIMINARY" if n >= LEVEL_PRELIMINARY else "INSUFFICIENT_EVIDENCE"


def _excluded(month, forecast, reason, detail, **extra):
    return {"month": month, "status": "EXCLUDED", "exclusion_reason": reason, "detail": detail,
            "official_forecast_id": forecast.get("forecast_run_id"), "official_method": forecast.get("method_type"), **extra}


def evaluate_month(*, month: str, forecast: dict, shadow: dict | None, actual_by_group: dict | None, actual_published_at, actual_run_id: str | None,
                   data_origin: str = "LAB_RUNTIME") -> dict:
    """One month. `forecast` = the sealed official forecast row; `shadow` = shadow_forecast.json found through the forecast id (or None)."""
    base = {"actual_run_id": actual_run_id, "actual_published_at": str(actual_published_at), "data_origin": data_origin}
    if shadow is None:
        return _excluded(month, forecast, "NO_SHADOW", "ไม่มี Shadow Forecast ที่บันทึกไว้คู่กับ Forecast นี้ (เช่น Seal ก่อนเปิดใช้ MLOps)", **base)
    if shadow.get("kind") != "OFFICIAL_LINKED" or shadow.get("official_forecast_id") != forecast.get("forecast_run_id"):
        return _excluded(month, forecast, "SHADOW_NOT_BOUND_TO_SEALED_FORECAST", "Shadow ไม่ได้ผูกกับ Forecast ID ที่ Seal จริง", **base)
    if shadow.get("target_month") != month:
        return _excluded(month, forecast, "SHADOW_TARGET_MISMATCH", "เดือนเป้าหมายของ Shadow ไม่ตรง", **base)
    if forecast.get("method_type") != "BASELINE":
        return _excluded(month, forecast, "OFFICIAL_NOT_BASELINE", "Official ของเดือนนี้ไม่ใช่ Baseline จึงไม่ใช่การเทียบ Champion Baseline กับ ML", **base)
    champion_key = "baseline_" + str(forecast.get("model_name"))
    champion_shadow = (shadow.get("baselines") or {}).get(champion_key)
    sealed = forecast.get("results") or {}
    if champion_shadow is None or shadow.get("ml") is None or any(sealed.get(g) is None for g in GROUPS):
        return _excluded(month, forecast, "ML_OR_BASELINE_MISSING", "ต้องมีคำทำนายทั้ง Baseline ที่เป็น Official และ ML จึงจะเทียบ (ไม่นับเดือนนี้ทั้งคู่)", **base)
    if any(abs(float(sealed[g]) - float(champion_shadow["groups"][g])) > 0.011 for g in GROUPS):
        return _excluded(month, forecast, "OFFICIAL_BASELINE_MISMATCH", "ค่า Baseline ใน Shadow ไม่ตรงกับ Official ที่ Seal (ไม่ใช้ผลที่ตรวจสอบไม่ได้)", **base)
    if actual_by_group is None or any(actual_by_group.get(g) is None for g in GROUPS):
        return _excluded(month, forecast, "ACTUAL_INCOMPLETE", "Actual ไม่ครบทั้ง 5 กลุ่มสินค้า", **base)
    try:
        before = _ts(shadow["created_at"]) < _ts(actual_published_at)
    except Exception:
        before = False
    if not before:
        return _excluded(month, forecast, "SHADOW_NOT_RECORDED_BEFORE_ACTUAL",
                         f"Shadow สร้างเมื่อ {shadow.get('created_at')} ไม่ก่อนเวลา Publish Actual {actual_published_at}", **base)
    if shadow.get("cutoff_month") != month_add(month, -1):
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
            "actual": {"groups": act, "shop": shop_act}, "champion_model": champion_key,
            "baseline": side({"model": champion_key, "model_version": champion_shadow["model_version"], "groups": sealed, "shop": sum(float(sealed[g]) for g in GROUPS)}),
            "ml": side(shadow["ml"])}


def summarize(rows: list[dict], *, stream, data_origin: str = "LAB_RUNTIME") -> dict:
    if data_origin not in ORIGINS:
        raise ValueError("MONITORING_DATA_ORIGIN_INVALID")
    foreign = [r for r in rows if r.get("data_origin") != data_origin]        # evidence of another origin (or none recorded) is never merged
    rows = [r for r in rows if r not in foreign]
    rows = rows + [{"month": r["month"], "status": "EXCLUDED", "exclusion_reason": "DATA_ORIGIN_MISMATCH",
                    "detail": f"หลักฐานเดือนนี้มาจาก {r.get('data_origin') or 'ไม่ระบุ'} ไม่ใช่ {data_origin} จึงไม่รวมในผล Monitoring ชุดนี้",
                    "row_data_origin": r.get("data_origin"), "official_forecast_id": r.get("official_forecast_id")} for r in foreign]
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
        status, msg = "RECOMMEND_REVIEW", "ผ่านทุกเงื่อนไข: เป็นคำแนะนำให้พิจารณาทบทวน Champion พร้อมหลักฐานด้านล่างเท่านั้น ระบบนี้ไม่มีฟังก์ชันเปลี่ยน Champion Official ยังเป็น Baseline"
    else:
        status, msg = "NOT_RECOMMENDED", "ยังไม่ผ่านเกณฑ์: " + "; ".join(r["label"] for r in rules if not r["passed"])
    return {"monitoring_version": MONITORING_VERSION, "stream": stream, "data_origin": data_origin, "window_months": WINDOW_MONTHS,
            "through_month": ev[-1]["month"] if ev else None,
            "pair": {"champion": "OFFICIAL_BASELINE_OF_EACH_MONTH", "challenger": CHALLENGER,
                     "note": "Champion = Baseline ที่ Seal เป็น Official ของแต่ละเดือน (ดีที่สุดระหว่าง trailing 3 กับ naive) · Ridge + Marketing อยู่ใน Experiment Only ไม่อยู่ในคู่เปรียบเทียบนี้"},
            "champion_models_by_month": {r["month"]: r["champion_model"] for r in ev},
            "counted_months": n, "evidence_level": level, "levels": {"preliminary_from": LEVEL_PRELIMINARY, "adequate_from": LEVEL_ADEQUATE},
            "cumulative": {"baseline": cb, "ml": cm, "groups": groups}, "monthly": monthly, "rows": ev, "excluded": excl,
            "recommendation": {"status": status, "message": msg, "rules": rules, "rule_values": RULES, "human_decision_required": True,
                               "auto_switch_champion": False, "auto_retrain": False, "champion_change_function_in_system": False,
                               "evidence": {"counted_months": [r["month"] for r in ev], "official_forecast_ids": [r["official_forecast_id"] for r in ev],
                                            "shadow_training_runs": [r["shadow_training_run_id"] for r in ev]}},
            "separation_note": "นับเฉพาะ Shadow Forecast ที่บันทึกก่อน Publish Actual · ไม่รวม Historical Evaluation, Experiment Only หรือ Backtest"}


def _load_rows(store, base: str, month: str) -> list[dict]:
    import json
    rows = []
    for i in range(WINDOW_MONTHS):                                               # this month and earlier ones of the same stream (rolling window)
        key = f"{base}/evaluations/{month_add(month, -i)}.json"
        if store.exists(key):
            rows.append(json.loads(store.get(key)))
    return rows


MAX_REVISIONS = 9


def _latest_revision(store, base: str, month: str):
    """(key, bytes) of the newest summary file of a through-month: `through=M.json`, then `through=M.rev1.json`, `.rev2` ... (None if none)."""
    key = f"{base}/summary/through={month}.json"
    if not store.exists(key):
        return None
    latest = (key, store.get(key))
    for n in range(1, MAX_REVISIONS + 1):
        nxt = f"{base}/summary/through={month}.rev{n}.json"
        if not store.exists(nxt):
            break
        latest = (nxt, store.get(nxt))
    return latest


def _write_summary(store, base: str, stream: str, month: str, data_origin: str) -> dict:
    """Immutable, deterministic summary files. If late evidence (a repaired earlier month) changes the content, a NEW revision file is written; older files stay as history."""
    summary = summarize(_load_rows(store, base, month), stream=stream, data_origin=data_origin)
    body = dumps(summary)
    latest = _latest_revision(store, base, month)
    if latest is None:
        put_new(store, f"{base}/summary/through={month}.json", body)
    elif latest[1] != body:
        n = int(latest[0].rsplit(".rev", 1)[1][:-5]) + 1 if ".rev" in latest[0] else 1
        if n > MAX_REVISIONS:
            raise StoreError("MONITORING_SUMMARY_REVISION_LIMIT")
        put_new(store, f"{base}/summary/through={month}.rev{n}.json", body)
    return summary


def record_month(store, *, stream: str, cycle, month: str, forecast: dict, actual_rows: list[dict], actual_published_at, actual_run_id: str | None,
                 data_origin: str = "LAB_RUNTIME", prefix: str = DEFAULT_PREFIX) -> dict:
    """Called when the actual of `month` is published (or by recovery). Evaluates it, stores the evaluation write-once and an immutable summary.
    `forecast` = the sealed official forecast {forecast_run_id, method_type, model_name, results{group: sealed value}}. Callers serialise per stream.
    Recovery: an evaluation that already exists is never recomputed; if its summary is missing it is rebuilt from the stored evidence only."""
    import json
    base = f"{prefix}/monitoring/{stream}"
    eval_key, summary_key = f"{base}/evaluations/{month}.json", f"{base}/summary/through={month}.json"
    if store.exists(eval_key):
        if store.exists(summary_key):
            return {"status": "ALREADY_RECORDED", "month": month}
        summary = _write_summary(store, base, stream, month, data_origin)         # crash between the two writes: rebuild the missing summary
        return {"status": "SUMMARY_REPAIRED", "month": month, "counted_months": summary["counted_months"], "evidence_level": summary["evidence_level"],
                "recommendation": summary["recommendation"]["status"]}
    pointer_key = f"{prefix}/monitoring/by_forecast/{forecast['forecast_run_id']}.json"
    shadow = None
    if store.exists(pointer_key):
        pointer = json.loads(store.get(pointer_key))
        skey = f"{pointer['run_path']}/shadow_forecast.json"
        shadow = json.loads(store.get(skey)) if store.exists(skey) else None         # a shadow that was never recorded is never created afterwards
    actual = {g: sum(float(r["net_revenue"]) for r in actual_rows if r["month"] == month and r["group"] == g) if any(r["month"] == month and r["group"] == g for r in actual_rows) else None
              for g in GROUPS}
    row = evaluate_month(month=month, forecast=forecast, shadow=shadow, actual_by_group=actual, actual_published_at=actual_published_at, actual_run_id=actual_run_id, data_origin=data_origin)
    row.update({"cycle": cycle, "stream": stream})
    if put_new(store, eval_key, dumps(row)) != "CREATED":
        return {"status": "ALREADY_RECORDED", "month": month}
    summary = _write_summary(store, base, stream, month, data_origin)
    return {"status": row["status"], "exclusion_reason": row.get("exclusion_reason"), "month": month, "counted_months": summary["counted_months"],
            "evidence_level": summary["evidence_level"], "recommendation": summary["recommendation"]["status"]}


def repair_stream(store, *, stream: str, cycle, published: list[dict], forecasts: dict, load_actual_rows, data_origin: str = "LAB_RUNTIME",
                  skip_months=(), prefix: str = DEFAULT_PREFIX) -> dict:
    """Idempotent recovery after a temporary monitoring failure.
    `published` = [{month, run_id, finished_at}] of months whose actual is Published; `forecasts` = {month: sealed official forecast};
    `load_actual_rows(run_id)` returns the published monthly rows of that run. Months already evaluated are untouched; months without a sealed
    forecast are skipped; the original Publish time is used for the 'shadow recorded before actual' check (never the time of the retry)."""
    out = {"evaluated": [], "summary_repaired": [], "unchanged": [], "skipped": []}
    for item in sorted(published, key=lambda x: x["month"]):
        month = item["month"]
        if month in skip_months or month not in forecasts:
            out["skipped"].append(month)
            continue
        base = f"{prefix}/monitoring/{stream}"
        had_eval = store.exists(f"{base}/evaluations/{month}.json")
        had_summary = store.exists(f"{base}/summary/through={month}.json")
        if had_eval and had_summary:
            out["unchanged"].append(month)
            continue
        res = record_month(store, stream=stream, cycle=cycle, month=month, forecast=forecasts[month],
                           actual_rows=[] if had_eval else load_actual_rows(item["run_id"]), actual_published_at=item["finished_at"],
                           actual_run_id=item["run_id"], data_origin=data_origin, prefix=prefix)
        (out["summary_repaired"] if had_eval else out["evaluated"]).append(month)
    if out["evaluated"]:                                                          # late evidence changes the newest through-month: publish it as a new revision
        base = f"{prefix}/monitoring/{stream}"
        evaluated_months = [it["month"] for it in published if store.exists(f"{base}/evaluations/{it['month']}.json")]
        if evaluated_months:
            _write_summary(store, base, stream, max(evaluated_months), data_origin)
            out["latest_summary_through"] = max(evaluated_months)
    return out
