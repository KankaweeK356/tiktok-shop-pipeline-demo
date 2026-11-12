"""SQLite OLTP ingest, business transformations and deterministic cost allocation."""
from __future__ import annotations
import json,sqlite3
from pathlib import Path
from decimal import Decimal,ROUND_HALF_UP
import pandas as pd
from .schema import init_er1,columns_for

PAID={'Paid','Shipped','Delivered'}
SOURCE_ORDER=['Dim_Product_Group','Dim_SKU','Dim_Creator','Dim_Campaign','Dim_Ad_Campaign',
  'Dim_Voucher','Bridge_Campaign_Product_Group','Bridge_Voucher_Product_Group',
  'Ref_Affiliate_Commission_Rule','Ref_Platform_Fee_Estimate_Rule','Ref_Business_Target','Ref_Cost_Policy',
  'Fact_Goods_Receipt','Fact_Goods_Receipt_Items','Fact_Orders','Fact_Order_Items',
  'Fact_Internal_Fulfillment','Fact_Marketing_Costs','Fact_Claim_Header','Fact_Claim_Details','Fact_Free_Samples']

class PipelineError(RuntimeError):
    def __init__(self,code,details):
        self.code=code;super().__init__(f'{code}: {details}')

def money(value):return float(Decimal(str(value)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP))
def frac(value):return Decimal(str(value))
def fetchdict(conn,sql,args=()):
    c=conn.execute(sql,args);return [dict(zip([v[0] for v in c.description],x)) for x in c.fetchall()]
def one(conn,sql,args=()):
    rows=fetchdict(conn,sql,args);return rows[0] if rows else None

def load_csv(file:Path,table:str):
    if not file.exists():raise PipelineError('E02_MISSING_SOURCE',f'{table}: {file.name}')
    df=pd.read_csv(file,encoding='utf-8-sig',dtype={'SKU_ID':str,'Product_Group_ID':str,'Order_ID':str})
    legal=set(columns_for(table));unknown=set(df.columns)-legal
    if unknown:raise PipelineError('E02_BAD_SOURCE_SCHEMA',f'{table} unknown: {sorted(unknown)}')
    for k in ['Order_ID','Order_Item_ID','SKU_ID','Product_Group_ID']:
        if k in df.columns and df[k].isna().any():raise PipelineError('E02_BAD_SOURCE_SCHEMA',f'{table}: empty {k}')
    return [{k:(None if pd.isna(v) else (int(v) if isinstance(v,bool) else v.item() if hasattr(v,'item') else v)) for k,v in row.items()}
            for row in df.to_dict(orient='records')]

def upsert(conn,table,rows):
    if not rows:return
    from .schema import parse_dbml,ROOT
    meta=next(t for t in parse_dbml(ROOT/'schemas/ER1_V3.dbml')[0] if t.name==table)
    keys=[c.name for c in meta.columns];pk=meta.pk
    for row in rows:
        fields=[k for k in keys if k in row]
        if not fields:continue
        upd=[k for k in fields if k not in pk]
        if upd:conflict=' ON CONFLICT ('+', '.join('"'+x+'"' for x in pk)+') DO UPDATE SET '+', '.join(f'"{x}"=excluded."{x}"' for x in upd)
        else:conflict=' ON CONFLICT DO NOTHING'
        sql=f'INSERT INTO "{table}" ('+', '.join(f'"{x}"' for x in fields)+') VALUES ('+', '.join('?' for _ in fields)+')'+conflict
        try:conn.execute(sql,[row[x] for x in fields])
        except sqlite3.IntegrityError as e:raise PipelineError('E01_INTEGRITY',f'{table}: {e}; row={str(row)[:220]}') from e

def eligible_price(conn,created_at,pgid,base):
    r=fetchdict(conn,"""SELECT b.Campaign_ID,b.Campaign_Selling_Price
      FROM Bridge_Campaign_Product_Group b JOIN Dim_Campaign c ON c.Campaign_ID=b.Campaign_ID
      WHERE b.Product_Group_ID=? AND b.Status='Active'
      AND date(?) BETWEEN date(b.Effective_From) AND date(b.Effective_To)
      AND date(?) BETWEEN date(c.Start_Date) AND date(c.End_Date)""",(pgid,created_at,created_at))
    if len(r)>1:raise PipelineError('T02_CAMPAIGN_OVERLAP',f'{pgid}, {created_at}')
    return (money(r[0]['Campaign_Selling_Price']),r[0]['Campaign_ID']) if r else (money(base),None)

def validate_campaigns(conn):
    rows=fetchdict(conn,"""SELECT a.Product_Group_ID,a.Enrollment_ID a_id,b.Enrollment_ID b_id
      FROM Bridge_Campaign_Product_Group a JOIN Bridge_Campaign_Product_Group b
      ON a.Product_Group_ID=b.Product_Group_ID AND a.Enrollment_ID<b.Enrollment_ID
      AND a.Status='Active' AND b.Status='Active'
      AND a.Effective_From<=b.Effective_To AND b.Effective_From<=a.Effective_To LIMIT 1""")
    if rows:raise PipelineError('T02_CAMPAIGN_OVERLAP',str(rows[0]))

def calculate_orders(conn,order_ids):
    validate_campaigns(conn)
    for oid in sorted(order_ids):
        o=one(conn,'SELECT * FROM Fact_Orders WHERE Order_ID=?',(oid,))
        if not o:raise PipelineError('E01_UNKNOWN_ORDER',oid)
        if o['Current_Status'] in PAID and not o['Paid_At']:raise PipelineError('T03_PAID_AT_REQUIRED',oid)
        if o['Current_Status']=='Cancelled' and o['Paid_At']:raise PipelineError('T03_REFUND_OUT_OF_SCOPE',oid)
        lines=fetchdict(conn,"""SELECT x.*,p.Product_Group_ID,p.Base_Selling_Price,
             p.Cost_Standard_Product FROM Fact_Order_Items x JOIN Dim_SKU s ON s.SKU_ID=x.SKU_ID
             JOIN Dim_Product_Group p ON p.Product_Group_ID=s.Product_Group_ID
             WHERE x.Order_ID=? ORDER BY x.Order_Item_ID""",(oid,))
        if not lines:raise PipelineError('E01_EMPTY_ORDER',oid)
        for x in lines:
            if x['Quantity']<=0:raise PipelineError('T03_NONPOSITIVE_QTY',x['Order_Item_ID'])
            if x['Base_Unit_Price_At_Sale'] is None or x['Unit_Selling_Price'] is None:
                base=money(x['Base_Selling_Price'])
                sale,cid=eligible_price(conn,o['Order_Created_At'],x['Product_Group_ID'],base)
                conn.execute('''UPDATE Fact_Order_Items SET Base_Unit_Price_At_Sale=?,
                  Unit_Selling_Price=?,Campaign_ID=? WHERE Order_Item_ID=?''',
                  (base,sale,cid,x['Order_Item_ID']))
                x['Base_Unit_Price_At_Sale']=base;x['Unit_Selling_Price']=sale;x['Campaign_ID']=cid
            if money(x['Base_Unit_Price_At_Sale'])!=money(x['Base_Selling_Price']):
                # Existing sales retain the snapshot even when master later changes.
                pass
            campaign_disc=money((float(x['Base_Unit_Price_At_Sale'])-float(x['Unit_Selling_Price']))*x['Quantity'])
            total=money(float(x['Unit_Selling_Price'])*x['Quantity'])
            if total<0 or campaign_disc<0:raise PipelineError('T03_INVALID_CAMPAIGN_PRICE',oid)
            conn.execute('''UPDATE Fact_Order_Items SET Campaign_Discount_Amount=?,Total_Selling_Amount=?
             WHERE Order_Item_ID=?''',(campaign_disc,total,x['Order_Item_ID']))
            x['Total_Selling_Amount']=total
        eligible=set()
        discount=0.0
        if o['Voucher_ID']:
            v=one(conn,'SELECT * FROM Dim_Voucher WHERE Voucher_ID=?',(o['Voucher_ID'],))
            if not v or not v['Is_Active']:raise PipelineError('T01_VOUCHER',oid+' inactive voucher')
            if not (v['Effective_From']<=o['Order_Created_At'][:10]<=v['Effective_To']):
                raise PipelineError('T01_VOUCHER',oid+' voucher outside date')
            if not 0<=float(v['Discount_Rate'])<=1:raise PipelineError('T01_VOUCHER',oid+' invalid rate')
            eligible={t['Product_Group_ID'] for t in fetchdict(conn,'SELECT Product_Group_ID FROM Bridge_Voucher_Product_Group WHERE Voucher_ID=?',(o['Voucher_ID'],))}
            eligible_total=money(sum(float(x['Total_Selling_Amount']) for x in lines if x['Product_Group_ID'] in eligible))
            if eligible_total>=float(v['Minimum_Spend_Amount']):
                discount=money(eligible_total*float(v['Discount_Rate']))
                if v['Maximum_Discount_Amount'] is not None:discount=min(discount,money(v['Maximum_Discount_Amount']))
                discount=min(discount,eligible_total)
        eligible_lines=[x for x in lines if x['Product_Group_ID'] in eligible]
        eligible_subtotal=sum(float(x['Total_Selling_Amount']) for x in eligible_lines)
        remaining=discount
        for idx,x in enumerate(eligible_lines):
            v_amt=money(remaining if idx==len(eligible_lines)-1 else discount*float(x['Total_Selling_Amount'])/eligible_subtotal) if discount else 0
            if v_amt>float(x['Total_Selling_Amount']):raise PipelineError('T01_VOUCHER',f'{oid}: voucher exceeds item')
            conn.execute('UPDATE Fact_Order_Items SET Voucher_Allocated_Amount=? WHERE Order_Item_ID=?',(v_amt,x['Order_Item_ID']))
            remaining=money(remaining-v_amt)
        for x in lines:
            if x not in eligible_lines:conn.execute('UPDATE Fact_Order_Items SET Voucher_Allocated_Amount=0 WHERE Order_Item_ID=?',(x['Order_Item_ID'],))
        total_gmv=money(sum(float(x['Total_Selling_Amount']) for x in lines))
        conn.execute('UPDATE Fact_Orders SET GMV_Total=?,Voucher_Seller_Cost=? WHERE Order_ID=?',(total_gmv,discount,oid))
        for x in lines:
            voucher=one(conn,'SELECT Voucher_Allocated_Amount FROM Fact_Order_Items WHERE Order_Item_ID=?',(x['Order_Item_ID'],))['Voucher_Allocated_Amount']
            net=money(float(x['Total_Selling_Amount'])-voucher)
            ar=one(conn,"""SELECT Affiliate_Commission_Rate FROM Ref_Affiliate_Commission_Rule
             WHERE Product_Group_ID=? AND Is_Active=1 AND Effective_From<=date(?)
               AND (Effective_To IS NULL OR Effective_To>=date(?))""",
             (x['Product_Group_ID'],o['Order_Created_At'],o['Order_Created_At']))
            if x['Creator_ID'] is not None and not ar:raise PipelineError('T03_MISSING_AFFILIATE_RULE',oid)
            af=money(net*float(ar['Affiliate_Commission_Rate'])) if x['Creator_ID'] else 0
            conn.execute('UPDATE Fact_Order_Items SET Fee_Affiliate_Payout=? WHERE Order_Item_ID=?',(af,x['Order_Item_ID']))
            if o['Current_Status'] in PAID:allocate_fifo(conn,x,o['Paid_At'])

def allocate_fifo(conn,item,paid_at):
    iid=item['Order_Item_ID']
    past=one(conn,'SELECT COALESCE(SUM(Allocated_Qty),0) qty FROM Fact_FIFO_Allocation WHERE Order_Item_ID=?',(iid,))['qty']
    missing=int(item['Quantity'])-int(past)
    if missing<=0:return
    lots=fetchdict(conn,"""SELECT gi.* FROM Fact_Goods_Receipt_Items gi
       JOIN Fact_Goods_Receipt r ON gi.Goods_Receipt_ID=r.Goods_Receipt_ID
       WHERE gi.SKU_ID=? AND gi.Remaining_Qty>0 ORDER BY r.Receipt_Date,gi.Goods_Receipt_Item_ID""",(item['SKU_ID'],))
    for lot in lots:
        if missing<=0:break
        take=min(missing,int(lot['Remaining_Qty']))
        allocid=f'FIFO-{iid}-{lot["Goods_Receipt_Item_ID"]}'
        cost=money(take*lot['Unit_Cost'])
        conn.execute('''INSERT INTO Fact_FIFO_Allocation
          (FIFO_Allocation_ID,Order_Item_ID,Goods_Receipt_Item_ID,Allocated_Qty,Unit_Cost,Allocated_Cost,Allocated_At)
          VALUES (?,?,?,?,?,?,?)''',(allocid,iid,lot['Goods_Receipt_Item_ID'],take,lot['Unit_Cost'],cost,paid_at))
        conn.execute('UPDATE Fact_Goods_Receipt_Items SET Remaining_Qty=Remaining_Qty-? WHERE Goods_Receipt_Item_ID=?',(take,lot['Goods_Receipt_Item_ID']))
        conn.execute('''INSERT OR IGNORE INTO Fact_Stock_Movement
         (Stock_Movement_ID,Event_Timestamp,SKU_ID,Movement_Type,Quantity,Unit_Cost,Total_Cost,Reference_ID,Source_System)
         VALUES (?,?,?,?,?,?,?,?,?)''',(f'MV-{allocid}',paid_at,item['SKU_ID'],'OUT_SALE',-take,lot['Unit_Cost'],cost,iid,'MOCK'))
        missing-=take
    if missing:raise PipelineError('E03_INSUFFICIENT_STOCK',iid)
    c=one(conn,'SELECT SUM(Allocated_Cost) c FROM Fact_FIFO_Allocation WHERE Order_Item_ID=?',(iid,))
    conn.execute('UPDATE Fact_Order_Items SET Total_COGS=? WHERE Order_Item_ID=?',(money(c['c']),iid))

def snapshots(conn,batch):
    latest=one(conn,'SELECT MAX(Order_Created_At) AS ts FROM Fact_Orders')['ts']
    ts=(latest[:10]+' 23:59:59') if latest else '2026-10-31 23:59:59'
    rows=fetchdict(conn,"""SELECT s.SKU_ID,p.Cost_Standard_Product,COALESCE(SUM(g.Remaining_Qty),0) rem
      FROM Dim_SKU s JOIN Dim_Product_Group p ON s.Product_Group_ID=p.Product_Group_ID
      LEFT JOIN Fact_Goods_Receipt_Items g ON g.SKU_ID=s.SKU_ID GROUP BY s.SKU_ID,p.Cost_Standard_Product""")
    for r in rows:
        free=int(r['rem'])
        conn.execute('''INSERT OR REPLACE INTO Fact_Inventory_Snapshot
        (Snapshot_ID,Snapshot_Timestamp,SKU_ID,Ending_Physical_Qty,TikTok_Listed_Available_Qty,
         TikTok_Order_Reserved_Qty,TikTok_Unavailable_Qty,Internal_Available_Qty,
         Claim_Buffer_Qty,Creator_Buffer_Qty,Free_Stock_Qty,Inventory_Value)
         VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
         (f'{batch}-{r["SKU_ID"]}',ts,r['SKU_ID'],free,free,0,0,free,0,0,free,money(free*r['Cost_Standard_Product'])))

def ingest(source_dir:Path,db_path:Path,batch:str,control_dir:Path):
    db_path.parent.mkdir(parents=True,exist_ok=True);control_dir.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(db_path);conn.row_factory=sqlite3.Row
    init_er1(conn)
    changed_orders=set(); changed_ads=set();changed_samples=set();changed_claims=set(); counts={}
    try:
        conn.execute('BEGIN')
        # A partial GitHub upload must fail with a clear Source missing error.
        expected=(SOURCE_ORDER if batch=='initial' else [
            'Fact_Orders','Fact_Order_Items','Fact_Internal_Fulfillment',
            'Fact_Marketing_Costs','Fact_Free_Samples'])
        missing=[t for t in expected if not (source_dir/f'{t}.csv').is_file()]
        if missing:
            raise PipelineError('E02_MISSING_SOURCE',', '.join(f'{t}.csv' for t in missing))
        for table in SOURCE_ORDER:
            p=source_dir/f'{table}.csv'
            if not p.exists():continue
            records=load_csv(p,table);counts[table]=len(records)
            if table=='Fact_Orders':
                for r in records:
                    prev=one(conn,'SELECT Current_Status,Paid_At FROM Fact_Orders WHERE Order_ID=?',(r['Order_ID'],))
                    if prev and prev['Current_Status'] in PAID and r['Current_Status']=='Cancelled':
                        raise PipelineError('T03_REFUND_OUT_OF_SCOPE',r['Order_ID'])
                changed_orders.update(x['Order_ID'] for x in records)
            elif table=='Fact_Order_Items':changed_orders.update(x['Order_ID'] for x in records)
            elif table=='Fact_Internal_Fulfillment':changed_orders.update(x['Order_ID'] for x in records)
            elif table=='Fact_Marketing_Costs':changed_ads.update(x['Ad_Record_ID'] for x in records)
            elif table=='Fact_Free_Samples':changed_samples.update(x['Sample_ID'] for x in records)
            elif table=='Fact_Claim_Details':changed_claims.update(x['Claim_Detail_ID'] for x in records)
            upsert(conn,table,records)
        # Sample COGS based on group reference price, not real observed source costs.
        conn.execute('''UPDATE Fact_Free_Samples SET Sample_COGS = ROUND(Sample_Quantity*(
           SELECT p.Cost_Standard_Product FROM Dim_SKU s JOIN Dim_Product_Group p
            ON s.Product_Group_ID=p.Product_Group_ID WHERE s.SKU_ID=Fact_Free_Samples.SKU_ID),2)
           WHERE Sample_COGS IS NULL''')
        calculate_orders(conn,changed_orders)
        snapshots(conn,batch)
        integrity=conn.execute('PRAGMA foreign_key_check').fetchall()
        if integrity:raise PipelineError('E01_INTEGRITY',str(integrity[:3]))
        conn.commit()
        item_ids=[]
        for oid in changed_orders:
            item_ids.extend(x[0] for x in conn.execute('SELECT Order_Item_ID FROM Fact_Order_Items WHERE Order_ID=?',(oid,)))
        affected={'batch':batch,'changed_order_ids':sorted(changed_orders),
           'changed_order_item_ids':sorted(set(item_ids)),'changed_ad_ids':sorted(changed_ads),
           'changed_sample_ids':sorted(changed_samples),'changed_claim_detail_ids':sorted(changed_claims),
           'source_counts':counts}
        (control_dir/f'changes_{batch}.json').write_text(json.dumps(affected,indent=2,ensure_ascii=False),encoding='utf-8')
        return {'input_records':sum(counts.values()),'modified_orders':len(changed_orders),'source_tables':len(counts)}
    except Exception:
        conn.rollback();raise
    finally:conn.close()
