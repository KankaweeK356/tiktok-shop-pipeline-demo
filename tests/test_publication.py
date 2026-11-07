"""Storage and GitHub publishing tests; do not need DuckDB/PyArrow or Colab."""
import json
from pathlib import Path
import pandas as pd
import pytest
from pipeline.publication import EvidenceNotReady,export_github_reports
from pipeline.drive_storage import CONFIRMATION,clear_drive_outputs,save_to_drive


def _create_mock_run(root:Path):
    main=root/'output'/'main'
    rep=main/'reports'
    control=main/'lake'/'control'
    rep.mkdir(parents=True);control.mkdir(parents=True)
    (main/'er1.sqlite').write_bytes(b'fake-db-for-test')
    (main/'er2.duckdb').write_bytes(b'fake-db-for-test')
    (main/'lake'/'raw').mkdir()
    (main/'lake'/'raw'/'data.parquet').write_bytes(b'fake-parquet-for-test')
    for stage in ('initial','incremental'):
        (control/f'checkpoint_{stage}.json').write_text(json.dumps({'completed':['ingest','extract','transform','load','validate']}))
    for stage in ('initial','incremental','final'):
        pd.DataFrame({'Check':['Net Revenue','Fact Mart'],'PASS':[True,True]}).to_csv(rep/f'functional_{stage}.csv',index=False)
    pd.DataFrame({'Source_Order_Item_ID':['ITEM01'],'Source':['source/initial/Fact_Order_Items.csv']}).to_csv(rep/'lineage_final.csv',index=False)
    pd.DataFrame({'Year_Month':['2026-10'],'Net_Revenue':[100],'Contribution_Profit':[20]}).to_csv(rep/'monthly_kpi.csv',index=False)
    pd.DataFrame({'Product_Group_ID':['PG01']}).to_csv(rep/'product_group_affiliate_scenario.csv',index=False)
    test=root/'output'/'test';test.mkdir(parents=True)
    pd.DataFrame({'case':['E01','E02','T01','T02','L01','L02'],'passed':[True]*6}).to_csv(test/'error_suite_summary.csv',index=False)
    perf=root/'output'/'performance';perf.mkdir()
    pd.DataFrame({'initial_source_orders':[100,300],'latency_seconds':[3.2,4.5], 'throughput_paid_items_per_second':[50,80]}).to_csv(perf/'performance_summary.csv',index=False)


def test_report_export_rejects_incomplete_run(tmp_path):
    with pytest.raises(EvidenceNotReady):export_github_reports(tmp_path)


def test_report_export_accepts_real_test_artifacts_and_zip_has_expected_paths(tmp_path):
    _create_mock_run(tmp_path)
    result=export_github_reports(tmp_path)
    import zipfile
    with zipfile.ZipFile(result['zip_path']) as z:
        files=set(z.namelist())
        assert 'reports/README.md' in files
        assert 'reports/monthly_kpi.csv' in files
        assert 'reports/performance.csv' in files
        assert 'reports/run_summary.json' in files
    assert result['summary']['error_cases_passed']==6


def test_report_export_rejects_failed_validation(tmp_path):
    _create_mock_run(tmp_path)
    pd.DataFrame({'Check':['bad'],'PASS':[False]}).to_csv(tmp_path/'output/main/reports/functional_final.csv',index=False)
    with pytest.raises(EvidenceNotReady):export_github_reports(tmp_path)


def test_drive_save_and_confirmed_clear_only_snapshots(tmp_path):
    _create_mock_run(tmp_path)
    mydrive=tmp_path/'MyDrive';mydrive.mkdir()
    unrelated=mydrive/'personal.txt';unrelated.write_text('KEEP')
    first=save_to_drive(tmp_path,mydrive)
    second=save_to_drive(tmp_path,mydrive)
    assert Path(first['path']).is_dir() and Path(second['path']).is_dir()
    assert Path(first['path']) != Path(second['path'])
    with pytest.raises(ValueError):clear_drive_outputs(mydrive,'')
    assert unrelated.read_text()=='KEEP'
    result=clear_drive_outputs(mydrive,CONFIRMATION)
    assert result['cleared_snapshots']==2
    assert unrelated.read_text()=='KEEP'
    assert (mydrive/'TikTok_Shop_Demo').exists()
    assert not (mydrive/'TikTok_Shop_Demo/snapshots').exists()


def test_drive_refuses_existing_unmarked_directory(tmp_path):
    _create_mock_run(tmp_path)
    mydrive=tmp_path/'MyDrive';(mydrive/'TikTok_Shop_Demo').mkdir(parents=True)
    (mydrive/'TikTok_Shop_Demo/other.txt').write_text('private')
    with pytest.raises(ValueError):save_to_drive(tmp_path,mydrive)
    with pytest.raises(ValueError):clear_drive_outputs(mydrive,CONFIRMATION)
    assert (mydrive/'TikTok_Shop_Demo/other.txt').read_text()=='private'
