"""DBML -> SQLite/DuckDB physical DDL; ER1=25, ER2=11 physical + 1 SQL view.
Keep the supplied V3/V5 files as the single schema reference; metadata/logs are out-of-core.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
@dataclass
class Column:
    name: str
    typ: str
    pk: bool=False
    not_null: bool=False
    unique: bool=False

@dataclass
class Table:
    name: str
    columns: list[Column]=field(default_factory=list)
    pk: list[str]=field(default_factory=list)
    uniques: list[list[str]]=field(default_factory=list)


def parse_dbml(path: Path) -> tuple[list[Table],list[tuple[str,str,str,str]]]:
    src=Path(path).read_text(encoding='utf-8')
    tables=[]; current=None; in_indexes=False; depth=0
    for line in src.splitlines():
        head=re.match(r'^Table\s+(\w+)\s*\{',line)
        if head:
            current=Table(head.group(1));tables.append(current);depth=1;in_indexes=False;continue
        if current is None:continue
        s=line.strip()
        if s.startswith('indexes {'):
            for match in re.finditer(r'\(([^)]+)\)\s*\[(pk|unique)\]',s):
                names=[a.strip() for a in match.group(1).split(',')]
                if match.group(2)=='pk':current.pk.extend(names)
                else:current.uniques.append(names)
            if '}' not in s:in_indexes=True;depth+=1
            continue
        if in_indexes:
            m=re.match(r'\(([^)]+)\)\s*\[(pk|unique)\]',s)
            if m:
                names=[a.strip() for a in m.group(1).split(',')]
                (current.pk if m.group(2)=='pk' else current.uniques).extend(names if m.group(2)=='pk' else [names])
            if s=='}':in_indexes=False;depth-=1
            continue
        m=re.match(r'^([A-Za-z_][\w]*)\s+(varchar|decimal|bigint|int|boolean|date|datetime)\b(.*)',s)
        if m:
            name,typ,opts=m.groups()
            col=Column(name,typ,'[pk' in opts or ', pk' in opts,
                       'not null' in opts, 'unique' in opts)
            current.columns.append(col)
            if col.pk:current.pk.append(name)
            if col.unique:current.uniques.append([name])
        if s=='}':
            depth-=1
            if depth==0:current=None
    refs=re.findall(r'^Ref:\s*(\w+)\.(\w+)\s*>\s*(\w+)\.(\w+)',src,flags=re.M)
    return tables,refs


def dtype(typ,engine):
    if typ=='varchar':return 'VARCHAR' if engine=='duckdb' else 'TEXT'
    if typ=='decimal':return 'DECIMAL(20,4)' if engine=='duckdb' else 'NUMERIC'
    if typ in ('int','bigint'):return 'BIGINT' if typ=='bigint' else 'INTEGER'
    if typ=='boolean':return 'BOOLEAN' if engine=='duckdb' else 'INTEGER'
    if typ=='datetime':return 'TIMESTAMP' if engine=='duckdb' else 'TEXT'
    if typ=='date':return 'DATE' if engine=='duckdb' else 'TEXT'
    raise ValueError(typ)

def create_table_sql(table:Table,engine:str,refs=()):
    bits=[]
    for c in table.columns:
        bits.append(f'"{c.name}" {dtype(c.typ,engine)}'+(' NOT NULL' if c.not_null else ''))
    if table.pk:bits.append('PRIMARY KEY ('+', '.join('"'+k+'"' for k in table.pk)+')')
    for uq in table.uniques:
        if uq != table.pk: bits.append('UNIQUE ('+', '.join('"'+k+'"' for k in uq)+')')
    if engine=='sqlite':
        for a,ac,b,bc in refs:
            if a==table.name:bits.append(f'FOREIGN KEY("{ac}") REFERENCES "{b}"("{bc}")')
    return f'CREATE TABLE IF NOT EXISTS "{table.name}" (\n '+',\n '.join(bits)+'\n)'

def init_er1(conn):
    ts,refs=parse_dbml(ROOT/'schemas/ER1_V3.dbml')
    assert len(ts)==25,f'ER1 table count changed: {len(ts)}'
    conn.execute('PRAGMA foreign_keys = ON')
    for t in ts:conn.execute(create_table_sql(t,'sqlite',refs))
    return ts

def init_er2(conn):
    ts,refs=parse_dbml(ROOT/'schemas/ER2_V5.dbml')
    assert len(ts)==12,f'ER2 DBML components changed: {len(ts)}'
    for t in ts:
        if t.name!='View_Shop_Monthly_KPI':conn.execute(create_table_sql(t,'duckdb',()))
    return ts

def columns_for(name,engine='er1'):
    ts,_=parse_dbml(ROOT/'schemas'/('ER1_V3.dbml' if engine=='er1' else 'ER2_V5.dbml'))
    return [c.name for t in ts if t.name==name for c in t.columns]
