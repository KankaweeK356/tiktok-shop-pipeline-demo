"""Dedicated error/recovery workspaces; systematic six-case suite, deterministic replay."""
from __future__ import annotations
import json,shutil,time,hashlib
from pathlib import Path
import pandas as pd
from .schema import ROOT
from .generate import generate
from .orchestrator import run_batch,reset
from .er1 import PipelineError

CASES=[('E01','Bad SKU FK','ingest'),('E02','Missing source file','ingest'),
       ('T01','Voucher rule breach','transform'),('T02','Campaign overlap','transform'),
       ('L01','Warehouse atomic rollback','load'),('L02','Duplicate batch replay','validate')]

def signature(ws):
    import duckdb
    conn=duckdb.connect(str(ws/'er2.duckdb'),read_only=True)
    result={
      'orders':conn.execute('SELECT COUNT(*) FROM Fact_Sales_Order_Item').fetchone()[0],
      'sales':round(float(conn.execute('SELECT COALESCE(SUM(Net_Revenue),0) FROM Fact_Sales_Order_Item').fetchone()[0]),2),
      'mart_sales':round(float(conn.execute('SELECT COALESCE(SUM(Net_Revenue),0) FROM Mart_Product_Group_Daily_Performance').fetchone()[0]),2),
      'ads':conn.execute('SELECT COUNT(*) FROM Fact_Ads_Daily').fetchone()[0]}
    conn.close();return result

def error_suite(test_root:Path|None=None,cases:list[str]|None=None,stop_after_detection:bool=False):
    root=Path(test_root or ROOT/'output'/'test')
    root.mkdir(exist_ok=True,parents=True)
    selected=set(cases or [x[0] for x in CASES])
    rows=[]
    for case,label,expected_stage in CASES:
        if case not in selected:continue
        work=root/f'case_{case}'
        if work.exists():shutil.rmtree(work)
        src=work/'source'
        generate(src,n_initial=80,n_incremental=12,seed=7400)
        ws=work/'workspace'
        reset(ws)
        fault_mode=case if case in {'T01','T02','L01'} else None
        broken=None
        if case=='E01':
            file=src/'initial'/'Fact_Order_Items.csv'
            broken=file.read_bytes()
            df=pd.read_csv(file);df.loc[0,'SKU_ID']='SKU_DOES_NOT_EXIST';df.to_csv(file,index=False)
        elif case=='E02':
            file=src/'initial'/'Fact_Orders.csv'
            broken=file.read_bytes();file.unlink()
        if case=='L02':
            run_batch(ws,'initial',src)
            run_batch(ws,'incremental',src)
            before=signature(ws)
            replay=run_batch(ws,'incremental',src)
            after=signature(ws)
            rows.append({'case':case,'stage':'incremental','injected_error':'Duplicate batch replay',
              'expected':'Unchanged KPI and counts','detected':'DUPLICATE_SKIPPED',
              'retry_from':'no stage (success checkpoint)','passed':before==after,
              'before':str(before),'after':str(after)})
            continue
        failed_stage=None;detected=None;retry_from=None
        try:
            run_batch(ws,'initial',src,inject_error=fault_mode)
        except Exception as e:
            report_path=ws/'reports'/'error_initial.json'
            err=json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
            failed_stage=err.get('stage');detected=err.get('error_code',type(e).__name__)
        finally:
            if broken is not None:file.write_bytes(broken)
        statefile=ws/'lake'/'control'/'checkpoint_initial.json'
        state=json.loads(statefile.read_text(encoding='utf-8')) if statefile.exists() else {'completed':[]}
        stages=['ingest','extract','transform','load','validate']
        retry_from=next((s for s in stages if s not in state['completed']),None)
        if stop_after_detection:
            detected_ok=failed_stage==expected_stage
            rows.append({'case':case,'stage':expected_stage,'injected_error':label,
              'expected':'Detect the prepared issue; wait for explicit recovery action',
              'detected':detected or 'NOT_DETECTED','retry_from':retry_from,
              'passed':detected_ok,'before':'FAILED' if failed_stage else 'NOT_FAILED',
              'after':'WAITING_FOR_RECOVERY'})
            continue
        passed=False
        if failed_stage==expected_stage:
            try:
                result=run_batch(ws,'initial',src,inject_error=None)
                passed=(result['status']=='SUCCESS' and result['functional_fails']==0 and retry_from==failed_stage)
            except Exception as e:
                detected=f'{detected}; RETRY_FAILED: {e}'
        rows.append({'case':case,'stage':expected_stage,'injected_error':label,
          'expected':'Fail -> fix -> resume from same failed stage -> PASS',
          'detected':detected or 'NOT_DETECTED','retry_from':retry_from,
          'passed':passed,'before':'FAILED' if failed_stage else 'NOT_FAILED',
          'after':'SUCCESS' if passed else 'FAILED'})
    df=pd.DataFrame(rows)
    report=root/'error_suite_summary.csv';df.to_csv(report,index=False)
    (root/'error_suite_summary.json').write_text(df.to_json(orient='records',force_ascii=False,indent=2),encoding='utf-8')
    return df


def performance_suite(root:Path|None=None,sizes=(100,300,800)):
    """End-to-end latency plus Paid-item throughput. Separate workspaces; sizes = generated initial orders.
    Use larger sizes=(1000,4000,12000) in Colab if runtime budget permits.
    """
    path=Path(root or ROOT/'output'/'performance')
    path.mkdir(parents=True,exist_ok=True)
    records=[]
    for count in sizes:
        case=path/f'orders_{count}'
        if case.exists():shutil.rmtree(case)
        source=case/'source';generate(source,n_initial=count,n_incremental=max(10,count//10),seed=7000)
        ws=case/'workspace';reset(ws)
        start=time.perf_counter();res=run_batch(ws,'initial',source)
        duration=time.perf_counter()-start
        records.append({'initial_source_orders':count,'paid_fact_items':res['paid_sales_rows'],
            'latency_seconds':round(duration,4),
            'throughput_paid_items_per_second':round(res['paid_sales_rows']/duration,2),
            'functional_checks_passed':res['functional_passes'],
            'environment':__import__('platform').platform()})
    df=pd.DataFrame(records);df.to_csv(path/'performance_summary.csv',index=False)
    return df
