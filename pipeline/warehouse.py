"""DuckDB Kimball load: delta upserts and targeted date/group mart rebuilds."""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime
import pandas as pd
from .schema import init_er2,ROOT,parse_dbml
from .er1 import PipelineError,money

DIMENSIONS=['Dim_Date','Dim_Product','Dim_Creator','Dim_Ad_Campaign','Dim_Voucher','Dim_Cost_Basis']
FACTS=['Fact_Sales_Order_Item','Fact_Ads_Daily','Fact_Free_Sample','Fact_Business_Target_Monthly']
NATURAL={'Fact_Sales_Order_Item':'Source_Order_Item_ID',
         'Fact_Ads_Daily':'Source_Ad_Record_ID','Fact_Free_Sample':'Source_Sample_ID',
         'Fact_Business_Target_Monthly':'Target_Year_Month'}
KEY={'Fact_Sales_Order_Item':'Sales_Fact_Key','Fact_Ads_Daily':'Ads_Fact_Key',
     'Fact_Free_Sample':'Sample_Fact_Key','Fact_Business_Target_Monthly':'Target_Fact_Key'}

def read_std(dir:Path,table:str):
    p=dir/f'{table}.parquet'
    if not p.exists():raise PipelineError('L03_MISSING_STANDARDIZED',str(p))
    return pd.read_parquet(p,engine='pyarrow')

def val(v):
    if v is None:return None
    try:
        if pd.isna(v):return None
    except (ValueError,TypeError):pass
    return v.item() if hasattr(v,'item') and not isinstance(v,(str,bytes)) else v

def upsert_row(con,table:str,row:dict,pk:list[str]):
    keys=list(row.keys());vs=[val(row[k]) for k in keys]
    rest=[k for k in keys if k not in pk]
    clause='ON CONFLICT('+','.join('"'+k+'"' for k in pk)+') DO UPDATE SET '+','.join(f'"{k}"=excluded."{k}"' for k in rest) if rest else 'ON CONFLICT DO NOTHING'
    q=f'INSERT INTO "{table}" ('+','.join(f'"{k}"' for k in keys)+') VALUES ('+','.join('?' for _ in keys)+') '+clause
    con.execute(q,vs)

def upsert_frame(con,table:str,df:pd.DataFrame,meta,auto_key=False):
    if df.empty:return 0
    pk=meta[table].pk
    next_key=None
    if auto_key:
        k=KEY[table]
        next_key=int(con.execute(f'SELECT COALESCE(MAX("{k}"),0) FROM "{table}"').fetchone()[0])+1
    count=0
    for row in df.to_dict('records'):
        if auto_key:
            keycol=KEY[table];natural=NATURAL[table]
            old=con.execute(f'SELECT "{keycol}" FROM "{table}" WHERE "{natural}"=?',[val(row[natural])]).fetchone()
            if old:row[keycol]=int(old[0])
            else:row[keycol]=next_key;next_key+=1
        upsert_row(con,table,row,pk)
        count+=1
    return count

def scalar(con,sql,args):
    result=con.execute(sql,args).fetchone()
    x=result[0] if result else None
    return float(x) if x is not None else 0.0

def rebuild_mart(con,std:Path,meta):
    dirty=json.loads((std/'dirty_dates_groups.json').read_text(encoding='utf-8'))
    claims=read_std(std,'claim_daily_external')
    claim_map={(int(x['Date_Key']),x['Product_Group_ID']):float(x['Claim_Cost']) for x in claims.to_dict('records')}
    con.execute("""CREATE OR REPLACE TEMP VIEW tmp_mart_sales AS
         SELECT s.Sales_Date_Key AS Date_Key,p.Product_Group_ID,
                SUM(s.Gross_Reference_Sales) Gross_Reference_Sales,
                SUM(s.Campaign_Price_Reduction) Campaign_Price_Reduction,
                SUM(s.Voucher_Allocated) Voucher_Discount,
                SUM(s.Net_Revenue) Net_Revenue,SUM(s.COGS) COGS,
                SUM(s.Platform_Fee_Cost) Platform_Fee_Cost,
                SUM(s.Fulfillment_Cost) Fulfillment_Cost,
                SUM(s.Affiliate_Cost) Affiliate_Cost,
                SUM(CASE WHEN b.Fulfillment_Basis='UNKNOWN' THEN 1 ELSE 0 END) Missing_Cost
          FROM Fact_Sales_Order_Item s JOIN Dim_Product p ON s.Product_Key=p.Product_Key
          JOIN Dim_Cost_Basis b ON s.Cost_Basis_Key=b.Cost_Basis_Key
          GROUP BY s.Sales_Date_Key,p.Product_Group_ID""")
    con.execute("""CREATE OR REPLACE TEMP VIEW tmp_mart_samples AS
        SELECT f.Dispatched_Date_Key AS Date_Key,p.Product_Group_ID,
               SUM(f.Total_Sample_Cost) AS Sample_Cost
        FROM Fact_Free_Sample f JOIN Dim_Product p ON f.Product_Key=p.Product_Key
        GROUP BY f.Dispatched_Date_Key,p.Product_Group_ID""")
    con.execute("""CREATE OR REPLACE TEMP VIEW tmp_mart_ads AS
        SELECT Date_Key,Product_Group_ID,SUM(Ads_Spend) Ads_Cost
        FROM Fact_Ads_Daily GROUP BY Date_Key,Product_Group_ID""")
    names=dict(con.execute('SELECT Product_Group_ID,MAX(Product_Group_Name) FROM Dim_Product GROUP BY 1').fetchall())
    n=0
    for x in dirty:
        d=int(x['Date_Key']);g=x['Product_Group_ID']
        sale=con.execute('SELECT * FROM tmp_mart_sales WHERE Date_Key=? AND Product_Group_ID=?',[d,g]).fetchone()
        sale_keys=['Date_Key','Product_Group_ID','Gross_Reference_Sales','Campaign_Price_Reduction',
                   'Voucher_Discount','Net_Revenue','COGS','Platform_Fee_Cost','Fulfillment_Cost','Affiliate_Cost','Missing_Cost']
        sr=dict(zip(sale_keys,sale)) if sale else {}
        ads=scalar(con,'SELECT Ads_Cost FROM tmp_mart_ads WHERE Date_Key=? AND Product_Group_ID=?',[d,g])
        samples=scalar(con,'SELECT Sample_Cost FROM tmp_mart_samples WHERE Date_Key=? AND Product_Group_ID=?',[d,g])
        claim=claim_map.get((d,g),0.)
        measure=['Gross_Reference_Sales','Campaign_Price_Reduction','Voucher_Discount',
                 'Net_Revenue','COGS','Platform_Fee_Cost','Fulfillment_Cost','Affiliate_Cost']
        row={'Date_Key':d,'Product_Group_ID':g,'Product_Group_Name':names.get(g)}
        row.update({k:money(sr.get(k,0)) for k in measure})
        row.update({'Ads_Cost':money(ads),'Sample_Cost':money(samples),'Claim_Cost':money(claim),
          'Calculated_At':datetime.utcnow().isoformat(sep=' ',timespec='seconds')})
        missing=bool(sr.get('Missing_Cost',0))
        row['Data_Cost_Basis']='INCOMPLETE' if missing else 'MOCK_ACTUAL_WITH_POLICY_FEE'
        row['Contribution_Profit']=(None if missing else money(row['Net_Revenue']-row['COGS']-
           row['Platform_Fee_Cost']-row['Fulfillment_Cost']-row['Affiliate_Cost']-
           row['Ads_Cost']-row['Sample_Cost']-row['Claim_Cost']))
        upsert_row(con,'Mart_Product_Group_Daily_Performance',row,meta['Mart_Product_Group_Daily_Performance'].pk)
        n+=1
    return n

def load(std:Path,warehouse_path:Path,inject_error=None):
    try:import duckdb
    except ImportError as e:raise RuntimeError('Missing duckdb. In Colab run %pip install -r requirements.txt') from e
    warehouse_path.parent.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect(str(warehouse_path))
    ts=init_er2(con);meta={t.name:t for t in ts}
    counts={}
    try:
        con.execute('BEGIN TRANSACTION')
        for name in DIMENSIONS:
            counts[name]=upsert_frame(con,name,read_std(std,name),meta)
        for name in FACTS:
            counts[name]=upsert_frame(con,name,read_std(std,name),meta,auto_key=name!='Fact_Business_Target_Monthly')
            if inject_error=='L01' and name=='Fact_Sales_Order_Item':
                raise PipelineError('L01_INJECTED_FAILURE','Warehouse load interrupted after Sales upserts; ROLLBACK expected')
        counts['Mart_Product_Group_Daily_Performance']=rebuild_mart(con,std,meta)
        view=(ROOT/'sql/monthly_kpi_view.sql').read_text(encoding='utf-8')
        # Avoid executing companion comment-only lines as standalone SQL in certain versions.
        view=view.split('-- Key checks:')[0]
        con.execute(view)
        con.execute('COMMIT')
        result={'loaded_rows':counts,'total_loaded':sum(counts.values()),
          'sales_fact_rows':con.execute('SELECT COUNT(*) FROM Fact_Sales_Order_Item').fetchone()[0]}
        return result
    except Exception:
        con.execute('ROLLBACK');raise
    finally:con.close()
