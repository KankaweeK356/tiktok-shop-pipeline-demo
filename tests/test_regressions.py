"""Regression checks for the Colab errors and incremental source correctness.

PyArrow/DuckDB are exercised in CI smoke and test_pipeline.py (with real libs).
The voucher test below simulates parquet IO for the limited type regression.
"""
from decimal import Decimal
import nbformat
import pandas as pd
from pipeline.generate import generate
from pipeline.er1 import ingest
from pipeline.lake import extract
from pipeline.transform import transform
from pipeline.quality import profit_protection_status
from pipeline.schema import ROOT


def test_decimal_profit_gate_accepts_mixed_numeric_types():
    assert profit_protection_status(Decimal('10.00'), 10.0) == 'PASS'
    assert profit_protection_status(Decimal('10.001'), 10.0) == 'PASS'
    assert profit_protection_status(Decimal('9.99'), 10.0) == 'FAIL'


def test_incremental_promotes_only_pending_orders(tmp_path):
    src=tmp_path/'source'
    data=generate(src,800,100,7202)
    initial=pd.read_csv(src/'initial'/'Fact_Orders.csv').set_index('Order_ID')
    later=pd.read_csv(src/'incremental'/'Fact_Orders.csv')
    existing=later[later.Order_ID.isin(initial.index)].set_index('Order_ID')
    assert data['pending_to_paid']==len(existing)==24
    assert set(initial.loc[existing.index,'Current_Status'])=={'Pending'}
    assert set(existing.Current_Status)=={'Paid'}
    assert initial.loc[existing.index,'Paid_At'].isna().all()


def test_voucher_active_stays_boolean_after_standardization(monkeypatch,tmp_path):
    monkeypatch.setattr(pd.DataFrame,'to_parquet',lambda self,path,**kw:self.to_pickle(path))
    monkeypatch.setattr(pd,'read_parquet',lambda path,**kw:pd.read_pickle(path))
    source=tmp_path/'source'
    generate(source,n_initial=80,n_incremental=12,seed=7400)
    ws=tmp_path/'output'/'main';control=ws/'lake'/'control'
    ingest(source/'initial',ws/'er1.sqlite','initial',control)
    import sqlite3
    con=sqlite3.connect(ws/'er1.sqlite')
    con.execute("UPDATE Dim_Voucher SET Is_Active=0 WHERE Voucher_ID='V05'")
    con.commit();con.close()
    extract(source/'initial',ws/'er1.sqlite',ws/'lake','initial')
    transform(ws/'lake',control,'initial')
    df=pd.read_pickle(ws/'lake'/'standardized'/'initial'/'Dim_Voucher.parquet')
    flags=df['Voucher_Active'].tolist()
    assert all(type(x) is bool for x in flags)
    assert True in flags and False in flags


def test_notebook_one_click_setup_is_valid():
    nb=nbformat.read(ROOT/'notebooks'/'TikTok_Shop_Demo.ipynb',as_version=4)
    nbformat.validate(nb)
    src=nb.cells[2].source
    assert 'KankaweeK356/tiktok-shop-pipeline-demo' in src
    # Setup must reuse an existing Colab checkout instead of pulling over a dirty tree.
    assert 'if target.exists():' in src
    assert "'clone'" in src
    assert "subprocess.check_call(['git','-C',str(target),'pull','--ff-only'])" not in src
    assert 'pipeline/orchestrator.py' in src


def test_t01_retry_with_legacy_integer_voucher_flag(monkeypatch,tmp_path):
    """Older Colab workaround set Voucher_Active=1; T01 must still recover."""
    import pyarrow.parquet as pq
    from pipeline.demo_tests import error_suite
    import pipeline.transform as transform_module

    monkeypatch.setitem(transform_module.NA_VOUCHER, 'Voucher_Active', 1)
    results=error_suite(tmp_path/'output'/'test',cases=['T01'])
    assert len(results)==1
    assert bool(results.iloc[0]['passed'])
    voucher_file=tmp_path/'output'/'test'/'case_T01'/'workspace'/'lake'/'standardized'/'initial'/'Dim_Voucher.parquet'
    field=pq.read_schema(voucher_file).field('Voucher_Active')
    assert field.type == __import__('pyarrow').bool_()
