"""Model comparison report (built only from a finished training run's own artifacts; nothing is recomputed or invented)."""
from __future__ import annotations

ROLE = {
    "baseline_trailing_3_month_mean": "BASELINE_OFFICIAL",
    "baseline_naive_previous_month": "BASELINE_REFERENCE",
    "ridge_base": "ML_OFFICIAL_CANDIDATE",
    "ridge_marketing": "ML_EXPERIMENTAL",
}
LABEL = {
    "baseline_trailing_3_month_mean": "Baseline: ค่าเฉลี่ย 3 เดือนล่าสุด",
    "baseline_naive_previous_month": "Baseline: เท่าเดือนก่อน (naive)",
    "ridge_base": "Ridge เดิม (ML ที่ใช้ในระบบ)",
    "ridge_marketing": "Ridge + Marketing (ทดลอง)",
}
METRIC_LEVEL = {
    "shop": "ระดับ Shop: รวมยอดคาดการณ์ของ 5 กลุ่มสินค้าเป็นยอดร้านต่อ origin แล้วเทียบกับยอดจริงของร้านเดือนนั้น "
            "WAPE = Σ|ผิดพลาดของร้าน| ÷ Σยอดจริงของร้าน, MAE = ค่าเฉลี่ย |ผิดพลาดของร้าน| ต่อ origin (บาท), Bias = ค่าเฉลี่ย (คาดการณ์ − จริง) ต่อ origin (บวก = คาดสูงเกิน)",
    "group": "ระดับ Product Group: WAPE ของแต่ละกลุ่ม PG01–PG05 = Σ|คาดการณ์ − จริง| ÷ Σจริง ของกลุ่มนั้นทุก origin (ใช้ตรวจว่าโมเดลไม่ทำให้กลุ่มใดแย่ลง)",
}


def build_report(bundle: dict) -> dict:
    run, ev, fm = bundle["run"], bundle["evaluation"], bundle["feature_meta"]
    same, wf = ev["models_same_origins"], ev["walk_forward"]
    base = same.get("baseline_trailing_3_month_mean", {}).get("shop_wape_pct")
    models = []
    for name, m in same.items():
        w = m.get("shop_wape_pct")
        models.append({"model": name, "label": LABEL.get(name, name), "role": ROLE.get(name, "UNKNOWN"), "status": m.get("status"),
                       "origins": m.get("origins"), "shop_wape_pct": w, "shop_mae": m.get("shop_mae"), "shop_bias": m.get("shop_bias"),
                       "group_wape_pct": m.get("group_wape_pct"),
                       "wape_vs_baseline_pp": None if (w is None or base is None) else round(w - base, 4),
                       "final_shop_prediction": ev["final_predictions"].get(name, {}).get("shop_prediction")})
    official = ev["official_logic_result"]
    n_valid = wf["n_valid_origins"]
    limits = [f"Walk-forward ที่ใช้เทียบทุกโมเดลมี {n_valid} origin ({', '.join(wf['origins']) or 'ไม่มี'}) ต้องมีอย่างน้อย {wf['min_origins_required']} จึงจะนับเป็น Eligible",
              "ข้อมูลจริงมีเพียง " + str(len(run["data_months"])) + " เดือน × 5 กลุ่มสินค้า จึงมีแถวฝึกน้อยกว่าจำนวนตัวแปรของ Ridge + Marketing มาก ผลที่ได้ไม่ใช่หลักฐานเรื่องคุณภาพโมเดล",
              "ผลเปรียบเทียบเป็นผลย้อนหลัง (Validation) ไม่ใช่ความแม่นยำของ Forecast ที่จะเกิดขึ้นจริง"]
    if run["evaluation_status"] != "ELIGIBLE":
        limits.insert(0, "สถานะ Experimental / Insufficient Validation: origin น้อยกว่าเกณฑ์ ห้ามใช้ผลนี้ตัดสินเลือกโมเดล")
    if any(m["role"] == "ML_EXPERIMENTAL" for m in models):
        limits.append("Ridge + Marketing เป็น Challenger ทดลองเท่านั้น ไม่เข้ากระบวนการเลือก Official ไม่ว่าคะแนนจะเป็นอย่างไร")
    post = ev.get("post_hoc_evaluation")
    forecast_vs_actual = None
    if post:
        forecast_vs_actual = {"label": post["label"], "actual_shop": post["actual_shop"], "models": {
            n: (None if v is None else {"label": LABEL.get(n, n), "shop_prediction": v["shop_prediction"], "shop_ape_pct": v["shop_ape_pct"],
                                         "shop_error_actual_minus_forecast": v["shop_error_actual_minus_forecast"]}) for n, v in post["models"].items()}}
    return {
        "report_version": "mlops-report-1", "training_run_id": run["training_run_id"], "kind": run["kind"], "target_month": run["target_month"],
        "evaluation_status": run["evaluation_status"],
        "data_window": {"months": run["data_months"], "first_month": run["data_months"][0], "cutoff_month": run["cutoff_month"],
                        "validation_origins": wf["origins"], "valid_origins": n_valid, "min_origins_required": wf["min_origins_required"],
                        "feature_version": fm["feature_version"], "feature_rows": fm["rows"], "labelled_rows": fm["labelled_rows"]},
        "metric_level": METRIC_LEVEL,
        "validation": {"section": "VALIDATION (walk-forward ย้อนหลัง ใช้เฉพาะข้อมูลถึง cutoff)", "models": models, "ranking_by_shop_wape": ev["ranking_by_shop_wape"]},
        "official_selection": {"decided_by": "monthly_forecast.generate_forecast (ตรรกะเดิม ไม่ถูกแก้)", "method_type": official["method_type"],
                               "model_name": official["model_name"], "shop_prediction": official["shop_prediction"], "reason": official["selection_reason"],
                               "ml_origins": official["ml_origins"], "validation_status": official["validation_status"],
                               "ridge_marketing_in_selection": False},
        "forecast_vs_actual": forecast_vs_actual or {"label": "ยังไม่มียอดจริงของเดือนเป้าหมาย", "actual_shop": None, "models": {}},
        "separation_note": "Validation = ผลย้อนหลังก่อนเดือนเป้าหมาย / Forecast vs Actual = เทียบยอดคาดการณ์กับยอดจริงหลังเดือนเป้าหมาย Publish แล้ว สองส่วนนี้ไม่นำมารวมหรือแทนกัน",
        "limitations": limits}


def render_markdown(r: dict) -> str:
    dw = r["data_window"]
    out = [f"# Model Comparison Report — เป้าหมาย {r['target_month']} ({r['kind']})", "",
           f"- Training Run: `{r['training_run_id']}`", f"- สถานะ Validation: **{r['evaluation_status']}**",
           f"- ข้อมูลที่ใช้: {dw['first_month']} → {dw['cutoff_month']} ({len(dw['months'])} เดือน), Feature `{dw['feature_version']}`",
           f"- Walk-forward origins ที่ใช้เทียบเท่ากันทุกโมเดล: **{dw['valid_origins']}** ({', '.join(dw['validation_origins'])}) · เกณฑ์ขั้นต่ำ {dw['min_origins_required']}", "",
           "## ระดับการคำนวณ Metrics", f"- {r['metric_level']['shop']}", f"- {r['metric_level']['group']}", "",
           "## 1) Validation (ย้อนหลัง · ระดับ Shop)", "", "| โมเดล | บทบาท | origins | WAPE % | MAE ฿ | Bias ฿ | WAPE ต่างจาก Baseline (pp) | คาดการณ์เดือนเป้าหมาย ฿ |", "|---|---|---|---|---|---|---|---|"]
    f = lambda v, d=2: "—" if v is None else f"{v:,.{d}f}"
    for m in r["validation"]["models"]:
        out.append(f"| {m['label']} | {m['role']} | {m['origins']} | {f(m['shop_wape_pct'])} | {f(m['shop_mae'], 0)} | {f(m['shop_bias'], 0)} | {f(m['wape_vs_baseline_pp'])} | {f(m['final_shop_prediction'])} |")
    out += ["", "### WAPE รายกลุ่มสินค้า (ระดับ Product Group)", "", "| โมเดล | PG01 | PG02 | PG03 | PG04 | PG05 |", "|---|---|---|---|---|---|"]
    for m in r["validation"]["models"]:
        g = m["group_wape_pct"] or {}
        out.append(f"| {m['label']} | " + " | ".join(f(g.get(k)) for k in ("PG01", "PG02", "PG03", "PG04", "PG05")) + " |")
    o = r["official_selection"]
    out += ["", "## 2) การเลือก Official Model", f"- ตัดสินโดย: {o['decided_by']}", f"- ผล: **{o['method_type']} / {o['model_name']}** ยอดร้าน ฿{f(o['shop_prediction'])}",
            f"- เหตุผล: {o['reason']}", f"- ML origins ที่ตรรกะเดิมนับ: {o['ml_origins']} · สถานะ: {o['validation_status']}", "- Ridge + Marketing ไม่อยู่ในการเลือก Official",
            "", "## 3) Forecast vs Actual (แยกจาก Validation)"]
    fa = r["forecast_vs_actual"]
    if fa["actual_shop"] is None:
        out.append(f"- {fa['label']}")
    else:
        out += [f"- {fa['label']}", f"- ยอดจริงของร้าน ฿{f(fa['actual_shop'])}", "", "| โมเดล | คาดการณ์ ฿ | APE % |", "|---|---|---|"]
        out += [f"| {v['label']} | {f(v['shop_prediction'])} | {f(v['shop_ape_pct'])} |" for v in fa["models"].values() if v]
    out += ["", f"> {r['separation_note']}", "", "## 4) ข้อจำกัด"] + [f"- {x}" for x in r["limitations"]]
    return "\n".join(out) + "\n"
