"""Full actual-engine smoke test for GitHub Actions (requires duckdb/pyarrow)."""
from __future__ import annotations
import json
from pathlib import Path
from .schema import ROOT
from .orchestrator import run_batch, reset
from .demo_tests import signature, error_suite, performance_suite
from .quality import verify, lineage
from .business import business_report
from .publication import export_github_reports


def main():
    ws=ROOT/'output'/'main'
    reset(ws)
    initial=run_batch(ws,'initial')
    before=signature(ws)
    next_run=run_batch(ws,'incremental')
    after=signature(ws)
    assert initial['functional_fails']==next_run['functional_fails']==0
    assert after['orders']>before['orders']
    assert run_batch(ws,'incremental')['status']=='SUCCESS'
    assert signature(ws)==after,'Replayed batch changed business metrics'
    final=verify(ws/'er1.sqlite',ws/'er2.duckdb',ws/'reports','final')
    assert final['failed']==0
    trace=lineage(ws/'er1.sqlite',ws/'er2.duckdb','final',ws/'lake'/'control',ws/'reports',limit=6)
    assert trace['traced_items']==6
    errors=error_suite(ROOT/'output'/'test')
    assert len(errors)==6 and errors['passed'].all()
    perf=performance_suite(ROOT/'output'/'performance',sizes=(100,300))
    assert len(perf)==2 and (perf['latency_seconds']>0).all()
    monthly,groups=business_report(ws/'er2.duckdb',ws/'reports')
    assert not monthly.empty and not groups.empty
    published=export_github_reports(ROOT)
    result={'run1':initial['status'],'run2':next_run['status'],
        'initial_paid_items':before['orders'],'after_incremental_paid_items':after['orders'],
        'replay_idempotent':True,'functional_checks':final['passed'],
        'error_recovery_passed':int(errors['passed'].sum()),
        'benchmark_sizes':perf['initial_source_orders'].tolist(),
        'reports_zip':str(Path(published['zip_path']).relative_to(ROOT))}
    print('FULL-ENGINE SMOKE RESULTS:')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result

if __name__=='__main__':main()
