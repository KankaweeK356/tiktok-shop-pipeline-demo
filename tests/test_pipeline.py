"""Run on Colab or locally once requirements are installed: pytest -q tests/test_pipeline.py."""
from pathlib import Path
import pandas as pd
import pytest
from pipeline.schema import ROOT,parse_dbml
from pipeline.generate import generate
from pipeline.orchestrator import run_batch
from pipeline.demo_tests import signature


def test_er_models_keep_counts():
    er1,refs1=parse_dbml(ROOT/'schemas/ER1_V3.dbml')
    er2,refs2=parse_dbml(ROOT/'schemas/ER2_V5.dbml')
    assert len(er1)==25 and len(refs1)==26
    assert len(er2)==12 and len(refs2)==12
    assert sum(t.name.startswith('Fact_') for t in er2)==4
    assert sum(t.name.startswith('Dim_') for t in er2)==6


def test_generator_is_deterministic(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b'
    generate(a,50,12,7202);generate(b,50,12,7202)
    for name in ['Fact_Orders.csv','Fact_Order_Items.csv','Dim_SKU.csv']:
        assert (a/'initial'/name).read_bytes()==(b/'initial'/name).read_bytes()
    assert len(pd.read_csv(a/'initial'/'Dim_SKU.csv'))==140


def test_end_to_end_incremental_and_replay(tmp_path):
    src=tmp_path/'source';generate(src,n_initial=80,n_incremental=20,seed=7222)
    ws=tmp_path/'output'/'main'
    one=run_batch(ws,'initial',src)
    before=signature(ws)
    two=run_batch(ws,'incremental',src)
    after=signature(ws)
    assert one['status']==two['status']=='SUCCESS'
    assert after['orders']>before['orders']
    assert two['functional_fails']==0
    assert run_batch(ws,'incremental',src)['status']=='SUCCESS'
    assert signature(ws)==after
