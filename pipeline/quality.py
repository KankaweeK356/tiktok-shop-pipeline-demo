"""Functional reconciliation and lineage from persisted SQLite -> DuckDB -> Mart/View."""
from __future__ import annotations
import sqlite3,json,hashlib
from pathlib import Path
from decimal import Decimal
from datetime import datetime
import pandas as pd
from .schema import parse_dbml,ROOT
from .er1 import PAID,money

def profit_protection_status(profit,required):
    """Compare DuckDB Decimal values without mixing with Python floats."""
    return 'PASS' if Decimal(str(profit)) >= Decimal(str(required)) else 'FAIL'

def verify(er1:Path,er2:Path,report_dir:Path,batch:str):
    import duckdb
    report_dir.mkdir(parents=True,exist_ok=True)
    src=sqlite3.connect(er1);dw=duckdb.connect(str(er2),read_only=True)
    checks=[];summary={}
    def add(name,got,expected,tol=0.011):
        if isinstance(got,(int,float)) and isinstance(expected,(int,float)):
            passed=abs(float(got)-float(expected))<=tol
        else:passed=got==expected
        checks.append({'Check':name,'Actual':got,'Expected':expected,'PASS':passed})
    try:
        assert src.execute('PRAGMA foreign_key_check').fetchall()==[]
        e1=[x[0] for x in src.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        e2=[x[0] for x in dw.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='BASE TABLE'").fetchall()]
        add('ER1 25 physical tables',len(e1),25)
        add('ER2 11 physical tables',len(e2),11)
        rows=src.execute("""SELECT COUNT(*) n,COALESCE(SUM(x.Total_Selling_Amount-x.Voucher_Allocated_Amount),0) net,
            COALESCE(SUM(x.Quantity*x.Base_Unit_Price_At_Sale),0) gross, COALESCE(SUM(x.Total_COGS),0) cogs,
            COALESCE(SUM(x.Fee_Affiliate_Payout),0) aff
          FROM Fact_Order_Items x JOIN Fact_Orders o ON x.Order_ID=o.Order_ID
          WHERE o.Current_Status IN ('Paid','Shipped','Delivered') AND o.Paid_At IS NOT NULL""").fetchone()
        fact=dw.execute('''SELECT COUNT(*),COALESCE(SUM(Net_Revenue),0),COALESCE(SUM(Gross_Reference_Sales),0),
         COALESCE(SUM(COGS),0),COALESCE(SUM(Affiliate_Cost),0) FROM Fact_Sales_Order_Item''').fetchone()
        for idx,key in enumerate(['Paid item count','Sales Net Revenue','Gross Reference Sales','Sold COGS','Affiliate Cost']):
            add(key,float(fact[idx]),float(rows[idx]))
        add('No duplicate Order Item',dw.execute('SELECT COUNT(*) FROM Fact_Sales_Order_Item').fetchone()[0],
            dw.execute('SELECT COUNT(DISTINCT Source_Order_Item_ID) FROM Fact_Sales_Order_Item').fetchone()[0])
        mismatches=src.execute('''SELECT COUNT(*) FROM (SELECT o.Order_ID,o.Voucher_Seller_Cost,SUM(x.Voucher_Allocated_Amount) used
           FROM Fact_Orders o JOIN Fact_Order_Items x ON x.Order_ID=o.Order_ID
           GROUP BY o.Order_ID HAVING ABS(COALESCE(o.Voucher_Seller_Cost,0)-COALESCE(used,0))>0.011)''').fetchone()[0]
        add('Voucher allocation mismatch',mismatches,0)
        invalid=dw.execute('''SELECT COUNT(*) FROM Fact_Sales_Order_Item
          WHERE ABS(Net_Revenue-(Sales_After_Campaign-Voucher_Allocated))>0.011
           OR ABS(Platform_Fee_Cost-ROUND(Net_Revenue*0.10,2))>0.011
           OR ABS(Gross_Reference_Sales-Quantity*Base_Unit_Price_At_Sale)>0.011''').fetchone()[0]
        add('Pricing & platform fee invalid rows',invalid,0)
        sales_net=dw.execute('SELECT COALESCE(SUM(Net_Revenue),0) FROM Fact_Sales_Order_Item').fetchone()[0]
        mart_net=dw.execute('SELECT COALESCE(SUM(Net_Revenue),0) FROM Mart_Product_Group_Daily_Performance').fetchone()[0]
        add('Fact-to-Mart Net Revenue',float(mart_net),float(sales_net))
        ads_cost=dw.execute('SELECT COALESCE(SUM(Ads_Spend),0) FROM Fact_Ads_Daily').fetchone()[0]
        mart_ads=dw.execute('SELECT COALESCE(SUM(Ads_Cost),0) FROM Mart_Product_Group_Daily_Performance').fetchone()[0]
        add('Fact Ads-to-Mart Ads',float(mart_ads),float(ads_cost))
        sample_cost=dw.execute('SELECT COALESCE(SUM(Total_Sample_Cost),0) FROM Fact_Free_Sample').fetchone()[0]
        mart_samples=dw.execute('SELECT COALESCE(SUM(Sample_Cost),0) FROM Mart_Product_Group_Daily_Performance').fetchone()[0]
        add('Fact Sample-to-Mart Sample',float(mart_samples),float(sample_cost))
        claim_src=src.execute('''SELECT COALESCE(SUM(COALESCE(Backend_Packing_Cost,0)+COALESCE(Backend_Shipping_Cost,0)
           +COALESCE(Replacement_Product_Cost,0)+COALESCE(Disposal_Loss_Cost,0)),0) FROM Fact_Claim_Details''').fetchone()[0]
        claim_mart=dw.execute('SELECT COALESCE(SUM(Claim_Cost),0) FROM Mart_Product_Group_Daily_Performance').fetchone()[0]
        add('ER1 Claims-to-Mart',float(claim_mart),float(claim_src))
        incomplete=dw.execute("SELECT COUNT(*) FROM Mart_Product_Group_Daily_Performance WHERE Data_Cost_Basis='INCOMPLETE'").fetchone()[0]
        if incomplete==0:
            profitcomponents=dw.execute('''SELECT COALESCE(SUM(Net_Revenue-COGS-Platform_Fee_Cost-Fulfillment_Cost-
              Affiliate_Cost-Ads_Cost-Sample_Cost-Claim_Cost),0) FROM Mart_Product_Group_Daily_Performance''').fetchone()[0]
            martprofit=dw.execute('SELECT COALESCE(SUM(Contribution_Profit),0) FROM Mart_Product_Group_Daily_Performance').fetchone()[0]
            add('Mart profit components',float(martprofit),float(profitcomponents))
        months=dw.execute('''SELECT Year_Month,Gross_Reference_Sales,Net_Revenue,Contribution_Profit,
          Minimum_Profit_Protection_Rate,Profit_Protection_Required,Profit_Protection_Headroom,
          Profit_Protection_Status FROM View_Shop_Monthly_KPI ORDER BY Year_Month''').fetchall()
        for month,gross,net,profit,rate,required,headroom,status in months:
            if profit is not None and rate is not None:
                add(f'{month} profit protection required',float(required),money(float(gross)*float(rate)))
                add(f'{month} profit headroom',float(headroom),money(float(profit)-float(required)))
                if gross>0:add(f'{month} profit protection status',status,profit_protection_status(profit,required))
        result={'batch':batch,'checks':len(checks),'passed':sum(x['PASS'] for x in checks),
          'failed':sum(not x['PASS'] for x in checks),
          'source_paid_item_count':rows[0], 'warehouse_sales_item_count':fact[0],
          'er1_net_revenue':money(rows[1]),'er2_net_revenue':money(fact[1]),
          'monthly_kpis':[{'month':m[0],'gross':float(m[1]),'net':float(m[2]),
             'profit':float(m[3]) if m[3] is not None else None,'protection':m[7]} for m in months]}
        pd.DataFrame(checks).to_csv(report_dir/f'functional_{batch}.csv',index=False)
        (report_dir/f'functional_{batch}.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
        if result['failed']:
            failed=[x['Check'] for x in checks if not x['PASS']]
            raise AssertionError(f'Functional validation FAIL: {failed}')
        return result
    finally:src.close();dw.close()

def lineage(er1:Path,er2:Path,batch:str,control_dir:Path,report_dir:Path,limit=8):
    import duckdb
    src=sqlite3.connect(er1);dw=duckdb.connect(str(er2),read_only=True)
    report_dir.mkdir(parents=True,exist_ok=True)
    try:
        # Determine the latest transformed batch for each item from real per-batch control receipts.
        item_processed_batch={}
        from .generate_classroom_source import BATCHES
        for b in (*BATCHES,'incremental'):
            receipt=Path(control_dir)/f'changes_{b}.json'
            if receipt.exists():
                for k in json.loads(receipt.read_text(encoding='utf-8')).get('changed_order_item_ids',[]):
                    item_processed_batch[k]=b
        ids=[r[0] for r in src.execute("""SELECT x.Order_Item_ID FROM Fact_Order_Items x
          JOIN Fact_Orders o ON x.Order_ID=o.Order_ID
          WHERE o.Current_Status IN ('Paid','Shipped','Delivered') ORDER BY x.Order_Item_ID LIMIT ?""",(limit,))]
        rec=[]
        for itemid in ids:
            row=src.execute('''SELECT x.Order_ID,x.Order_Item_ID,x.SKU_ID,o.Paid_At,
             x.Total_Selling_Amount-x.Voucher_Allocated_Amount,x.Total_COGS
             FROM Fact_Order_Items x JOIN Fact_Orders o ON o.Order_ID=x.Order_ID
             WHERE x.Order_Item_ID=?''',(itemid,)).fetchone()
            dwrow=dw.execute('''SELECT f.Source_Order_Item_ID,f.Net_Revenue,f.COGS,f.Sales_Date_Key,
                p.Product_Group_ID,p.Product_Group_Name
               FROM Fact_Sales_Order_Item f JOIN Dim_Product p ON f.Product_Key=p.Product_Key
               WHERE f.Source_Order_Item_ID=?''',[itemid]).fetchone()
            assert dwrow and abs(float(dwrow[1])-float(row[4]))<0.011
            mart=dw.execute('''SELECT Net_Revenue,Contribution_Profit FROM Mart_Product_Group_Daily_Performance
                WHERE Date_Key=? AND Product_Group_ID=?''',[dwrow[3],dwrow[4]]).fetchone()
            processed=item_processed_batch.get(itemid,'initial')
            if row[0].startswith("H") and len(row[0])>=9 and row[0][1:7].isdigit():
                source_month=row[0][1:7]
                year,month=int(source_month[:4]),int(source_month[4:])
                origin="initial" if (year,month)==(2026,1) else (
                    f"incremental_{(year-2026)*12+month-1:02d}")
            else:
                origin="initial" if row[0].startswith(("OCT","H")) else "incremental_01"
            month=str(dwrow[3])[:4]+'-'+str(dwrow[3])[4:6]
            rec.append({'Batch_Inspected':batch,'Source_Order_Item_ID':itemid,
                'Source':f'source/{origin}/Fact_Order_Items.csv',
                'ER1_Order_ID':row[0],'ER1_SKU_ID':row[2],
                'ER1_Net_Revenue':round(float(row[4]),2),
                'Lake_Raw':f'lake/raw/{processed}/Fact_Order_Items.parquet',
                'Lake_Standardized':f'lake/standardized/{processed}/Fact_Sales_Order_Item.parquet',
                'ER2_Sales_Item_ID':dwrow[0], 'ER2_Net_Revenue':float(dwrow[1]),
                'Sales_Date_Key':int(dwrow[3]),'Product_Group_ID':dwrow[4],
                'Mart_Group_Daily_Revenue':float(mart[0]),
                'Monthly_KPI_Year_Month':month,
                'Note':'This line CONTRIBUTES to group/day Mart, not a one-to-one KPI row'})
        path=report_dir/f'lineage_{batch}.csv';pd.DataFrame(rec).to_csv(path,index=False)
        return {'traced_items':len(rec),'file':str(path)}
    finally:src.close();dw.close()
