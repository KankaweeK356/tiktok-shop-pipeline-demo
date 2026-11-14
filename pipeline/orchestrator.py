"""Reusable per-stage checkpoints, failure audit, manual reset and batch replay guards."""
from __future__ import annotations
import json,time,shutil,traceback,os
from datetime import datetime,timezone
from pathlib import Path
from .schema import ROOT
from .er1 import ingest,PipelineError
from .lake import extract
from .transform import transform
from .warehouse import load
from .quality import verify,lineage
from .neon_source import sync_sqlite_to_neon, extract_neon

STAGES=['ingest','extract','transform','load','validate']

def reset(root:Path):
    root=Path(root).resolve()
    if ROOT not in root.parents and root.name not in ('main','test','perf_small','perf_medium','perf_large'):
        # Also accepts generated runtime under /content, with explicit root provided by caller.
        if root.name not in ('main','test') and 'output' not in root.parts:
            raise ValueError('Reset requires explicit main/test workspace path under output/')
    if root.exists():shutil.rmtree(root)
    root.mkdir(parents=True,exist_ok=True)
    return root

def stage_log(control:Path,record):
    p=control/'stage_history.jsonl'
    with open(p,'a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')

def run_batch(workspace:Path,batch='initial',source_root:Path|None=None,inject_error=None,resume=True,stop_after:str|None=None):
    """Run the full batch by default, or stop at one requested stage for a staged demo.
    Completed stages are checkpointed, so advancing to the next stage never repeats
    a successful ingest/extract/transform/load. Existing callers behave unchanged.
    """
    if stop_after is not None and stop_after not in STAGES:
        raise ValueError(f'Invalid stop_after stage: {stop_after}')
    workspace=Path(workspace);source_root=Path(source_root or os.environ.get('CLASSROOM_SOURCE_ROOT') or ROOT/'source')
    from .generate_classroom_source import BATCHES
    if batch not in (*BATCHES,'incremental','incremental_02_error'):raise ValueError('Unknown Source delivery')
    if batch!='initial' and not (workspace/'er1.sqlite').exists():
        raise PipelineError('NEEDS_INITIAL','Run 1 before Run 2')
    control=workspace/'lake'/'control';reports=workspace/'reports'
    control.mkdir(parents=True,exist_ok=True);reports.mkdir(parents=True,exist_ok=True)
    state_file=control/f'checkpoint_{batch}.json'
    state=json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() and resume else {'batch':batch,'completed':[],'metrics':{}}
    source=source_root/batch
    neon_url=os.environ.get('NEON_DEMO_DATABASE_URL','')
    def task(stage):
        if stage=='ingest':
            result=ingest(source,workspace/'er1.sqlite',batch,control)
            if neon_url:
                result['neon_sync']=sync_sqlite_to_neon(workspace/'er1.sqlite',neon_url)
            return result
        if stage=='extract':
            return (extract_neon(source,neon_url,workspace/'lake',batch)
                    if neon_url else
                    extract(source,workspace/'er1.sqlite',workspace/'lake',batch))
        if stage=='transform':return transform(workspace/'lake',control,batch,inject_error=inject_error)
        if stage=='load':return load(workspace/'lake'/'standardized'/batch,workspace/'er2.duckdb',inject_error=inject_error)
        if stage=='validate':
            result=verify(workspace/'er1.sqlite',workspace/'er2.duckdb',reports,batch)
            result['lineage']=lineage(workspace/'er1.sqlite',workspace/'er2.duckdb',batch,control,reports)
            return result
    for stage in STAGES:
        if stage in state['completed']:
            if stage==stop_after:
                break
            continue
        start=time.perf_counter()
        try:
            result=task(stage)
            elapsed=round(time.perf_counter()-start,4)
            state['completed'].append(stage)
            state['metrics'][stage]={'elapsed_seconds':elapsed,'result':result}
            state_file.write_text(json.dumps(state,indent=2,ensure_ascii=False),encoding='utf-8')
            stage_log(control,{'batch':batch,'stage':stage,'status':'SUCCESS','elapsed_seconds':elapsed,
               'at':datetime.now(timezone.utc).isoformat()})
        except Exception as e:
            elapsed=round(time.perf_counter()-start,4)
            code=e.code if isinstance(e,PipelineError) else type(e).__name__
            stage_log(control,{'batch':batch,'stage':stage,'status':'FAILED','error_code':code,
                'detail':str(e),'elapsed_seconds':elapsed,'at':datetime.now(timezone.utc).isoformat()})
            governance=workspace/'lake'/'governance'/'quarantine'
            governance.mkdir(parents=True,exist_ok=True)
            (governance/f'{batch}_{stage}_{code}.json').write_text(json.dumps({
                'batch':batch,'stage':stage,'error_code':code,'description':str(e),
                'source_hint':'Inspect Source CSV and corresponding Raw Parquet; no successful stage was committed'},
                indent=2,ensure_ascii=False),encoding='utf-8')
            (reports/f'error_{batch}.json').write_text(json.dumps({'batch':batch,'stage':stage,
              'status':'FAILED','error_code':code,'error':str(e),'recovery':'Retry same batch after fixing '+stage,
              'completed_before_failure':state['completed']},indent=2,ensure_ascii=False),encoding='utf-8')
            raise
        if stage==stop_after:
            break
    metrics=state['metrics']
    if not set(STAGES).issubset(state['completed']):
        seconds=sum(float(v['elapsed_seconds']) for v in metrics.values())
        return {'batch':batch,'status':'PARTIAL','stopped_after':stop_after,
            'completed':state['completed'],'elapsed_seconds':round(seconds,4),
            'metrics':metrics}
    seconds=sum(float(metrics[s]['elapsed_seconds']) for s in STAGES)
    return {'batch':batch,'status':'SUCCESS','completed':state['completed'],
       'elapsed_seconds':round(seconds,4),'metrics':metrics,
       'paid_sales_rows':metrics['validate']['result']['warehouse_sales_item_count'],
       'net_revenue':metrics['validate']['result']['er2_net_revenue'],
       'functional_passes':metrics['validate']['result']['passed'],
       'functional_fails':metrics['validate']['result']['failed']}

def summary(workspace):
    workspace=Path(workspace);rows=[]
    for batch in ('initial','incremental'):
        p=workspace/'lake'/'control'/f'checkpoint_{batch}.json'
        if p.exists():
            state=json.loads(p.read_text(encoding='utf-8'))
            for stage,meta in state['metrics'].items():
                n=meta['result'].get('input_records') or meta['result'].get('raw_records') or meta['result'].get('total_loaded') or meta['result'].get('changed_sales') or 0
                secs=meta['elapsed_seconds']
                rows.append({'batch':batch,'stage':stage,'seconds':secs,
                  'records_processed':n,'throughput_records_s':round(n/secs,2) if secs else None})
    import pandas as pd
    df=pd.DataFrame(rows)
    report=workspace/'reports';report.mkdir(exist_ok=True,parents=True)
    df.to_csv(report/'stage_performance.csv',index=False)
    return df
