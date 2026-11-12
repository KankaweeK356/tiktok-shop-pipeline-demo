"""Export *actually executed* run evidence for manual publishing to GitHub.

No GitHub token or GitHub write permission is requested.  The published snapshot is
assembled only after the source run, both incremental checkpoints, full functional
checks, error suite, and performance report are available and passing.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd


class EvidenceNotReady(RuntimeError):
    pass


def _pass_column(series: pd.Series) -> bool:
    return series.astype(str).str.strip().str.lower().isin({'true', '1', 'pass'}).all()


def export_github_reports(project_root: Path) -> dict:
    """Create output/github_report_upload.zip containing reports/ for manual GitHub upload.

    Checks that the actual Colab/host pipeline was executed. Does not submit to GitHub.
    Never reads example or placeholder reports in the git source as proof of success.
    """
    project_root = Path(project_root).resolve()
    output = project_root / 'output'
    main = output / 'main'
    checks = main / 'reports'
    control = main / 'lake' / 'control'
    test = output / 'test'
    perf = output / 'performance'
    selected = {
        'run1_functional.csv': checks / 'functional_initial.csv',
        'run2_functional.csv': checks / 'functional_incremental.csv',
        'final_functional.csv': checks / 'functional_final.csv',
        'lineage.csv': checks / 'lineage_final.csv',
        'monthly_kpi.csv': checks / 'monthly_kpi.csv',
        'product_group_affiliate_scenario.csv': checks / 'product_group_affiliate_scenario.csv',
        'error_recovery.csv': test / 'error_suite_summary.csv',
        'performance.csv': perf / 'performance_summary.csv',
    }
    required = [main/'er1.sqlite', main/'er2.duckdb', *selected.values(),
                control/'checkpoint_initial.json', control/'checkpoint_incremental.json']
    missing = [str(p.relative_to(project_root)) for p in required if not p.is_file()]
    if missing:
        raise EvidenceNotReady('ยังไม่มีผลรันครบ: ' + ', '.join(missing) +
                               ' — รัน Run 1, Run 2, Sections 03–05 บน Colab ให้ครบก่อน')

    checkpoints = {}
    for batch in ('initial', 'incremental'):
        data = json.loads((control/f'checkpoint_{batch}.json').read_text(encoding='utf-8'))
        required_stages = {'ingest','extract','transform','load','validate'}
        if not required_stages.issubset(data.get('completed', [])):
            raise EvidenceNotReady(f'{batch}: ขั้นตอน Pipeline ยังไม่ครบ')
        checkpoints[batch] = data

    counts = {}
    for name in ('run1_functional.csv','run2_functional.csv','final_functional.csv'):
        df = pd.read_csv(selected[name])
        if df.empty or 'PASS' not in df or not _pass_column(df['PASS']):
            raise EvidenceNotReady(f'{name}: Functional Test ยังไม่ผ่านครบ')
        counts[name] = len(df)

    err = pd.read_csv(selected['error_recovery.csv'])
    if (err.empty or 'passed' not in err or not _pass_column(err['passed']) or
            set(err['case'].astype(str)) != {'E01','E02','T01','T02','L01','L02'}):
        raise EvidenceNotReady('Error Recovery ยังไม่มีผลทดสอบครบ 6 กรณีที่ผ่านทั้งหมด')

    benchmark = pd.read_csv(selected['performance.csv'])
    if benchmark.empty or not {'latency_seconds','throughput_paid_items_per_second'}.issubset(benchmark.columns):
        raise EvidenceNotReady('Performance Report ไม่ครบ')
    latency = pd.to_numeric(benchmark['latency_seconds'],errors='coerce')
    throughput = pd.to_numeric(benchmark['throughput_paid_items_per_second'],errors='coerce')
    if not (latency.gt(0).all() and throughput.ge(0).all()):
        raise EvidenceNotReady('Performance มีค่าที่ไม่ถูกต้อง')

    monthly = pd.read_csv(selected['monthly_kpi.csv'])
    if monthly.empty or not {'Year_Month','Net_Revenue','Contribution_Profit'}.issubset(monthly.columns):
        raise EvidenceNotReady('Monthly KPI Report ยังไม่ครบ')
    lineage = pd.read_csv(selected['lineage.csv'])
    if lineage.empty or 'Source_Order_Item_ID' not in lineage:
        raise EvidenceNotReady('Lineage Report ยังไม่ครบ')

    prepared = output/'github_report_upload'
    if prepared.exists():
        shutil.rmtree(prepared)
    reports = prepared/'reports'
    reports.mkdir(parents=True)
    for name, origin in selected.items():
        shutil.copy2(origin, reports/name)

    source_count = sum(counts.values())
    created_at = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    summary = {
        'generated_at_utc': created_at,
        'source': 'Executed pipeline on current Colab/runtime (Mock source data)',
        'er1_schema': 'ER 1 V3', 'er2_schema': 'ER 2 V5',
        'run1_functional_checks': counts['run1_functional.csv'],
        'run2_functional_checks': counts['run2_functional.csv'],
        'final_functional_checks': counts['final_functional.csv'],
        'error_cases_passed': int(_pass_column(err['passed']) and len(err)),
        'performance_data_sizes': benchmark['initial_source_orders'].astype(int).tolist(),
        'monthly_periods': monthly['Year_Month'].astype(str).tolist(),
        'lineage_rows': len(lineage),
        'note': 'Performance times reflect the environment used during this actual execution. Mock transactions, not real TikTok data.'
    }
    (reports/'run_summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    note = f'''# ผลการรัน Demo — TikTok Shop Data Pipeline

**อัปเดตผลรัน:** {created_at}

รายงานในโฟลเดอร์นี้สร้างจากการรัน **Source → SQLite ER 1 → Parquet Lake → DuckDB ER 2** พร้อมทดสอบ Incremental, Functional, Error Recovery และ Performance ในสภาพแวดล้อมของผู้รัน

**ข้อมูลทั้งหมดเป็นข้อมูลจำลอง** ไม่มีการเชื่อม TikTok Shop จริง ตัวเลขยอดขายและกำไรจึงไม่ใช่ผลประกอบการจริง

## ดูผลตรงไหน

| ไฟล์ | ใช้ตรวจอะไร |
|---|---|
| [run1_functional.csv](run1_functional.csv) | ผลตรวจยอดหลัง Initial Load ({counts['run1_functional.csv']} ข้อ) |
| [run2_functional.csv](run2_functional.csv) | ผลตรวจหลัง Incremental Load ({counts['run2_functional.csv']} ข้อ) |
| [final_functional.csv](final_functional.csv) | ผลตรวจล่าสุด ({counts['final_functional.csv']} ข้อ) |
| [lineage.csv](lineage.csv) | ตัวอย่างที่มาข้อมูลจาก Source ถึง KPI ({len(lineage)} รายการ) |
| [error_recovery.csv](error_recovery.csv) | ผล Fail → Fix → Retry ครบ 6 กรณี |
| [performance.csv](performance.csv) | Latency และ Throughput ที่วัดระหว่างรัน |
| [monthly_kpi.csv](monthly_kpi.csv) | ยอดขาย กำไร และ Profit Protection รายเดือน |
| [product_group_affiliate_scenario.csv](product_group_affiliate_scenario.csv) | ทดลองเพดาน Affiliate Commission ตาม Product Group |
| [run_summary.json](run_summary.json) | วันที่สร้างรายงาน และสรุปผลการตรวจ |

## ทดลองเอง

[เปิด Demo บน Google Colab](https://colab.research.google.com/github/KankaweeK356/tiktok-shop-pipeline-demo/blob/feature/classroom-demo-evidence-foundation/notebooks/TikTok_Shop_Step_by_Step_Demo.ipynb)

> รายงานชุดนี้เป็น snapshot ที่เจ้าของ Repository อัปโหลดหลังทดสอบ ไม่เปลี่ยนอัตโนมัติเมื่อผู้อื่นเปิด Colab ผลสดของแต่ละคนแสดงใน Notebook ของตนเอง และอาจแตกต่างกันด้าน Performance
'''
    (reports/'README.md').write_text(note, encoding='utf-8')
    archive = output/'github_report_upload.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for f in sorted(reports.iterdir()):
            z.write(f,arcname=f'reports/{f.name}')
    return {'zip_path': str(archive), 'reports_folder':str(reports), 'summary':summary}

