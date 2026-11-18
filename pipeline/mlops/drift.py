"""Drift monitoring: ALERT and RECOMMEND only. Nothing here retrains, schedules a retrain or touches a forecast.

Input drift  = features of the inference rows (the cutoff month) vs the labelled training rows that the models learned from.
Performance  = realised error vs validation error; needs several realised months, otherwise INSUFFICIENT_EVIDENCE.
"""
from __future__ import annotations

import math

from .definitions import FEATURES

MIN_REFERENCE_ORIGINS = 4        # labelled origin months required before a distribution comparison is trusted
MIN_CURRENT_VALUES = 5           # one value per product group
MIN_REALISED_MONTHS = 3
WATCH_Z, ALERT_Z, WATCH_OUT, ALERT_OUT = 1.0, 2.0, 0.2, 0.4
ORDER = {"STABLE": 0, "WATCH": 1, "ALERT": 2}
MONITORED = [f["name"] for f in FEATURES if f["type"] in ("number", "ratio") and f["name"] != "days_in_label_month"]


def _stat(values):
    n = len(values)
    mean = sum(values) / n
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / n) if n else 0.0
    return mean, std


def compute_drift(feature_rows: list[dict], *, validation_wape_pct: float | None = None, realised: list[dict] | None = None) -> dict:
    ref = [r for r in feature_rows if not r["is_inference"]]
    cur = [r for r in feature_rows if r["is_inference"]]
    ref_origins = sorted({r["origin_month"] for r in ref})
    base = {"drift_version": "mlops-drift-1", "mode": "ALERT_AND_RECOMMEND_ONLY", "auto_retrain": False,
            "sealed_forecast_modified": False,
            "reference": {"rows": len(ref), "origins": ref_origins}, "current": {"rows": len(cur), "origin": cur[0]["origin_month"] if cur else None},
            "thresholds": {"min_reference_origins": MIN_REFERENCE_ORIGINS, "min_current_values": MIN_CURRENT_VALUES, "watch_z": WATCH_Z, "alert_z": ALERT_Z,
                           "watch_outside_share": WATCH_OUT, "alert_outside_share": ALERT_OUT, "min_realised_months": MIN_REALISED_MONTHS},
            "scope_note": "เปรียบเทียบ Feature ของเดือน cutoff (1 จุดเวลา × 5 กลุ่ม) กับช่วงฝึก เป็นสัญญาณเตือนเบื้องต้น ไม่ใช่การพิสูจน์ว่าโมเดลเสื่อม"}
    features = {}
    if len(ref_origins) < MIN_REFERENCE_ORIGINS or len(cur) < MIN_CURRENT_VALUES:
        input_status, why = "INSUFFICIENT_EVIDENCE", f"ข้อมูลอ้างอิงมี {len(ref_origins)} origin (ต้อง ≥ {MIN_REFERENCE_ORIGINS}) และค่าปัจจุบัน {len(cur)} (ต้อง ≥ {MIN_CURRENT_VALUES})"
    else:
        for name in MONITORED:
            rv = [r[name] for r in ref if r.get(name) is not None]
            cv = [r[name] for r in cur if r.get(name) is not None]
            if len(rv) < MIN_REFERENCE_ORIGINS * 2 or len(cv) < MIN_CURRENT_VALUES:
                features[name] = {"status": "INSUFFICIENT_EVIDENCE", "reference_n": len(rv), "current_n": len(cv),
                                  "reason": "ค่าที่ใช้ได้ไม่พอ (ค่าขาดไม่ถูกเติมเป็น 0)"}
                continue
            m_ref, s_ref = _stat(rv)
            if s_ref == 0:
                features[name] = {"status": "INSUFFICIENT_EVIDENCE", "reference_n": len(rv), "current_n": len(cv), "reason": "ช่วงอ้างอิงไม่มีความแปรปรวน"}
                continue
            m_cur, _ = _stat(cv)
            z = (m_cur - m_ref) / s_ref
            outside = sum(1 for v in cv if v < min(rv) or v > max(rv)) / len(cv)
            status = ("ALERT" if abs(z) >= ALERT_Z or outside >= ALERT_OUT else "WATCH" if abs(z) >= WATCH_Z or outside >= WATCH_OUT else "STABLE")
            features[name] = {"status": status, "reference_mean": round(m_ref, 6), "reference_std": round(s_ref, 6), "current_mean": round(m_cur, 6),
                              "mean_shift_z": round(z, 4), "share_outside_reference_range": round(outside, 4), "reference_n": len(rv), "current_n": len(cv)}
        scored = [v["status"] for v in features.values() if v["status"] in ORDER]
        if not scored:
            input_status, why = "INSUFFICIENT_EVIDENCE", "ไม่มี Feature ใดมีข้อมูลพอเปรียบเทียบ"
        else:
            input_status = max(scored, key=ORDER.get)
            why = {"STABLE": "ไม่พบการเปลี่ยนของ Feature เกินเกณฑ์", "WATCH": "บาง Feature เริ่มห่างจากช่วงฝึก ควรเฝ้าดู",
                   "ALERT": "บาง Feature ห่างจากช่วงฝึกเกินเกณฑ์"}[input_status]
    # performance (forecast vs actual) drift: never concluded from fewer than MIN_REALISED_MONTHS realised months
    realised = realised or []
    if len(realised) < MIN_REALISED_MONTHS:
        perf = {"status": "INSUFFICIENT_EVIDENCE", "realised_months": len(realised), "required": MIN_REALISED_MONTHS, "observations": realised,
                "reason": f"มียอดจริงเทียบแล้ว {len(realised)} เดือน (ต้อง ≥ {MIN_REALISED_MONTHS}) จึงยังสรุป Performance Drift ไม่ได้"}
    else:
        mean_ape = sum(o["ape_pct"] for o in realised) / len(realised)
        ratio = None if not validation_wape_pct else mean_ape / validation_wape_pct
        st = "STABLE" if ratio is None or ratio < 1.5 else "WATCH" if ratio < 2.0 else "ALERT"
        perf = {"status": st, "realised_months": len(realised), "mean_ape_pct": round(mean_ape, 4), "validation_wape_pct": validation_wape_pct,
                "error_ratio": None if ratio is None else round(ratio, 3), "observations": realised}
    statuses = [input_status, perf["status"]]
    if "ALERT" in statuses:
        overall, rec = "ALERT", "RECOMMEND_RETRAIN_REVIEW"
        msg = "แนะนำให้ผู้รับผิดชอบทบทวนและพิจารณา Retrain เอง ระบบไม่ Retrain อัตโนมัติ และไม่แก้ Forecast ที่ Seal แล้ว"
    elif "WATCH" in statuses:
        overall, rec = "WATCH", "MONITOR"
        msg = "เฝ้าดูต่อในรอบถัดไป ยังไม่แนะนำให้ Retrain"
    elif input_status == "INSUFFICIENT_EVIDENCE":
        overall, rec = "INSUFFICIENT_EVIDENCE", "COLLECT_MORE_DATA"
        msg = "ข้อมูลยังไม่พอ ไม่สรุปว่ามี Drift และไม่แนะนำ Retrain"
    else:
        overall, rec = "STABLE", "NO_ACTION"
        msg = "ไม่มีสัญญาณที่ต้องดำเนินการ" + (" (Performance Drift ยังสรุปไม่ได้เพราะยอดจริงไม่พอ)" if perf["status"] == "INSUFFICIENT_EVIDENCE" else "")
    return {**base, "overall_status": overall, "recommendation": rec, "message": msg,
            "input_drift": {"status": input_status, "reason": why, "features": features}, "performance_drift": perf}
