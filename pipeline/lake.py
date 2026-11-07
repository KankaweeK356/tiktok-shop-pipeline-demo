"""Ingest source receipts to Landing and extract all 25 source tables as auditable Raw Parquet snapshots.
ER2 changes are selected by batch keys at the Standardized -> Warehouse boundary.
"""
from __future__ import annotations
from pathlib import Path
import sqlite3, shutil,json,hashlib
import pandas as pd
from .schema import ROOT,parse_dbml

def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        while True:
            b=f.read(1024*1024)
            if not b:break
            h.update(b)
    return h.hexdigest()

def extract(source_dir:Path,db_path:Path,lake_dir:Path,batch:str):
    landing=lake_dir/'landing'/batch;raw=lake_dir/'raw'/batch
    landing.mkdir(parents=True,exist_ok=True);raw.mkdir(parents=True,exist_ok=True)
    manifest={'batch_id':batch,'landing':{},'raw':{},'mode':'full ER1 lookup snapshots; ER2 delta selected via batch changes'}
    for f in sorted(source_dir.glob('*.csv')):
        dst=landing/f.name;shutil.copy2(f,dst)
        manifest['landing'][f.name]={'sha256':sha256(dst),'bytes':dst.stat().st_size}
    conn=sqlite3.connect(db_path)
    try:
        tables,_=parse_dbml(ROOT/'schemas/ER1_V3.dbml')
        for table in tables:
            frame=pd.read_sql_query(f'SELECT * FROM "{table.name}"',conn)
            p=raw/f'{table.name}.parquet';frame.to_parquet(p,index=False,engine='pyarrow')
            manifest['raw'][table.name]={'records':len(frame),'sha256':sha256(p),
                                         'relative_path':str(p.relative_to(lake_dir))}
    finally:conn.close()
    control=lake_dir/'control';control.mkdir(parents=True,exist_ok=True)
    governance=lake_dir/'governance';governance.mkdir(parents=True,exist_ok=True)
    (governance/f'schema_receipt_{batch}.json').write_text(json.dumps({
        'batch':batch,'er1_table_count':len(tables),
        'table_columns':{t.name:[c.name for c in t.columns] for t in tables},
        'source_file_checksums':manifest['landing']},indent=2,ensure_ascii=False),encoding='utf-8')
    (control/f'manifest_{batch}.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    return {'parquet_tables':len(tables),'source_files':len(manifest['landing']),
            'raw_records':sum(x['records'] for x in manifest['raw'].values())}
