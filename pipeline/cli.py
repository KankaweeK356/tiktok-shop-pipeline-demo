"""Command-line entry points; Google Colab uses the same modules."""
from __future__ import annotations
import argparse,json
from .schema import ROOT
from .orchestrator import run_batch,reset,summary
from .quality import verify,lineage
from .demo_tests import error_suite,performance_suite

def main():
    p=argparse.ArgumentParser(description='TikTok Shop reproducible pipeline')
    p.add_argument('action',choices=['reset','run1','run2','verify','errors','performance','summary'])
    p.add_argument('--cases',default='all',help='specific comma-separated case IDs or all')
    p.add_argument('--sizes',default='100,300,800',help='comma-separated initial order counts')
    p.add_argument('--workspace',default=str(ROOT/'output'/'main'))
    args=p.parse_args();ws=ROOT/'output'/'main' if args.workspace=='main' else __import__('pathlib').Path(args.workspace)
    if args.action=='reset':print('RESET',reset(ws))
    elif args.action in ('run1','run2'):
        mode='initial' if args.action=='run1' else 'incremental'
        result=run_batch(ws,mode);print(json.dumps(result,indent=2,ensure_ascii=False))
    elif args.action=='verify':
        result=verify(ws/'er1.sqlite',ws/'er2.duckdb',ws/'reports','manual')
        result['lineage']=lineage(ws/'er1.sqlite',ws/'er2.duckdb','manual',ws/'lake'/'control',ws/'reports')
        print(json.dumps(result,indent=2,ensure_ascii=False))
    elif args.action=='errors':
        cases=None if args.cases=='all' else [x.strip() for x in args.cases.split(',')]
        print(error_suite(cases=cases).to_string(index=False))
    elif args.action=='performance':
        sizes=tuple(int(x) for x in args.sizes.split(','))
        print(performance_suite(sizes=sizes).to_string(index=False))
    elif args.action=='summary':print(summary(ws).to_string(index=False))

if __name__=='__main__':main()
