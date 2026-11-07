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
    import duckdb
    con=duckdb.connect(str(ws/'er2.duckdb'),read_only=True)
    before_oct=float(con.execute(
        "SELECT Net_Revenue FROM View_Shop_Monthly_KPI WHERE Year_Month='2026-10'").fetchone()[0])
    con.close()
    two=run_batch(ws,'incremental',src)
    after=signature(ws)
    con=duckdb.connect(str(ws/'er2.duckdb'),read_only=True)
    after_oct=float(con.execute(
        "SELECT Net_Revenue FROM View_Shop_Monthly_KPI WHERE Year_Month='2026-10'").fetchone()[0])
    con.close()
    assert abs(after_oct-before_oct)<0.011
    assert one['status']==two['status']=='SUCCESS'
    assert after['orders']>before['orders']
    assert two['functional_fails']==0
    assert run_batch(ws,'incremental',src)['status']=='SUCCESS'
    assert signature(ws)==after


def test_colab_notebook_setup_can_be_rerun():
    """Section 00 must not pull over a locally changed Colab checkout."""
    import ast
    import json
    notebook = json.loads((ROOT/'notebooks'/'TikTok_Shop_Demo.ipynb').read_text(encoding='utf-8'))
    setup = ''.join(notebook['cells'][2]['source'])
    tree = ast.parse(setup)
    subprocess_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in ('check_call', 'run', 'check_output')
    ]
    for call in subprocess_calls:
        for argument in call.args:
            if isinstance(argument, ast.List):
                literals = [element.value for element in argument.elts
                            if isinstance(element, ast.Constant) and isinstance(element.value, str)]
                assert 'pull' not in literals, 'Colab setup must not git pull in an existing runtime'
    assert "if target.exists():" in setup
    assert "'clone'" in setup
    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            ast.parse(''.join(cell['source']))
