"""Deterministic, entirely synthetic one-shop commerce source files (NOT real TikTok extracts)."""
from __future__ import annotations
from pathlib import Path
import random
from datetime import datetime,timedelta
import pandas as pd
from .schema import ROOT

GROUPS=[('PG01','คอกลม',199),('PG02','คอวี',229),('PG03','คอเต่า',279),('PG04','Crop',189),('PG05','Oversize',259)]
COLORS=['Black','White','Brown','Navy','Grey','Red','Pink']
SIZES=['S','M','L','XL']
PAID={'Paid','Shipped','Delivered'}

def dump(path:Path,table:str,rows):
    if not rows:return
    pd.DataFrame(rows).to_csv(path/f'{table}.csv',index=False,encoding='utf-8-sig')

def orders(n:int,seed:int,start:datetime,prefix:str,skus:list[str],voucher_ids:list[str],existing_pending=None):
    r=random.Random(seed);hdr=[];items=[];fulfill=[]
    for i in range(n):
        oid=f'{prefix}{i+1:05d}'
        created=start+timedelta(minutes=r.randint(0,30*24*60) if prefix=='OCT' else r.randint(0,20*60))
        status=r.choices(['Paid','Shipped','Delivered','Pending','Cancelled'],[44,25,16,11,4])[0] if prefix=='OCT' else r.choices(['Paid','Shipped','Pending','Cancelled'],[65,20,12,3])[0]
        if prefix=='OCT' and i<24:created=datetime(2026,10,31,16,0)+timedelta(minutes=i);status='Pending'
        paid=(created+timedelta(minutes=r.randint(4,125))) if status in PAID else None
        # An October initial snapshot cannot contain events paid after the October cutoff.
        if prefix=='OCT' and paid and paid.date()>datetime(2026,10,31).date():
            status='Pending';paid=None
        shipped=(paid+timedelta(hours=r.randint(3,28))) if paid and status in ('Shipped','Delivered') else None
        delivered=(shipped+timedelta(days=r.randint(1,4))) if shipped and status=='Delivered' else None
        # Only expose statuses actually reached by 2026-10-31 in the initial snapshot.
        if prefix=='OCT' and shipped and shipped.date()>datetime(2026,10,31).date():
            shipped=None;delivered=None;status='Paid'
        elif prefix=='OCT' and delivered and delivered.date()>datetime(2026,10,31).date():
            delivered=None;status='Shipped'
        voucher=r.choice(voucher_ids+[None,None,None])
        hdr.append({'Order_ID':oid,'Order_Created_At':created.isoformat(' '),'Current_Status':status,
                    'Voucher_ID':voucher,'GMV_Total':None,'Voucher_Seller_Cost':None,
                    'Shipping_Fee_Collected':0,'Shipping_Mode':'TikTok_Platform',
                    'Paid_At':paid.isoformat(' ') if paid else None,
                    'Shipped_At':shipped.isoformat(' ') if shipped else None,
                    'Delivered_At':delivered.isoformat(' ') if delivered else None,
                    'Cancelled_At':(created+timedelta(minutes=15)).isoformat(' ') if status=='Cancelled' else None})
        count=r.choices([1,2,3],[56,37,7])[0]
        chosen=r.sample(skus,count)
        for k,sku in enumerate(chosen):
            items.append({'Order_Item_ID':f'{oid}-I{k+1}', 'Source_Order_Item_ID':f'{oid}-I{k+1}',
                'Order_ID':oid,'SKU_ID':sku,'Quantity':r.choice([1,1,1,2,2,3]),
                'Creator_ID':r.choice([None,None,None,'CR01','CR02','CR03','CR04','CR05','CR06']),
                'Campaign_ID':None,'Base_Unit_Price_At_Sale':None,'Unit_Selling_Price':None,
                'Campaign_Discount_Amount':None,'Voucher_Allocated_Amount':0,
                'Total_Selling_Amount':None,'Total_COGS':None,'Fee_Affiliate_Payout':None,
                'Created_At':created.isoformat(' ')})
        if status in PAID:
            fulfill.append({'Fulfillment_ID':f'FUL-{oid}','Order_ID':oid,
              'Secondary_Packaging_Cost':r.choice([2,3,4]),'Packing_Labor_Cost':r.choice([4,5,6]),
              'Actual_Shipping_Cost':r.choice([0,4,6]),
              'Fulfillment_Timestamp':(min(paid+timedelta(hours=8),datetime(2026,10,31,23,59,59)) if prefix=='OCT' else paid+timedelta(hours=8)).isoformat(' ')})
    return hdr,items,fulfill

def generate(target:Path|None=None,n_initial=800,n_incremental=100,seed=7202):
    base=Path(target) if target else ROOT/'source'
    i=base/'initial';u=base/'incremental'
    i.mkdir(parents=True,exist_ok=True);u.mkdir(parents=True,exist_ok=True)
    for p in list(i.glob('*.csv'))+list(u.glob('*.csv')):p.unlink()
    pg=[{'Product_Group_ID':g,'Product_Group_Name':name,'Base_Selling_Price':price,
         'Cost_Standard_Product':round(price*.4,2),'Status':'Active'} for g,name,price in GROUPS]
    dump(i,'Dim_Product_Group',pg)
    sku=[]
    for group,name,_ in GROUPS:
        for color in COLORS:
            for size in SIZES:
                code=f'{group}-{color[:2].upper()}-{size}'
                sku.append({'SKU_ID':code,'Product_Group_ID':group,'SKU_Name':f'{name} {color} {size}',
                            'Color':color,'Size':size,'Status':'Active'})
    assert len(sku)==140 and len({x['SKU_ID'] for x in sku})==140
    dump(i,'Dim_SKU',sku)
    dump(i,'Dim_Creator',[{'Creator_ID':f'CR{k:02d}','Creator_Name':f'Synthetic Creator {k:02d}',
                         'Creator_Type':'Affiliate','Status':'Active'} for k in range(1,9)])
    campaigns=[('CAM01','October Sale','Flash Sale','2026-10-05','2026-10-10'),
               ('CAM02','Mid-October','Promotion','2026-10-20','2026-10-25'),
               ('CAM03','November Bridge','Promotion','2026-10-28','2026-11-05')]
    dump(i,'Dim_Campaign',[dict(zip(['Campaign_ID','Campaign_Name','Campaign_Type','Start_Date','End_Date'],c)) for c in campaigns])
    campaign_bridge=[]
    for ca,groups,fromd,tod in [
        ('CAM01',[('PG01',175),('PG02',199)],'2026-10-05','2026-10-10'),
        ('CAM02',[('PG03',245),('PG04',165)],'2026-10-20','2026-10-25'),
        ('CAM03',[('PG01',185),('PG05',225)],'2026-10-28','2026-11-05')]:
        for pgid,price in groups:
            campaign_bridge.append({'Enrollment_ID':f'EN-{ca}-{pgid}', 'Campaign_ID':ca,
             'Product_Group_ID':pgid,'Campaign_Selling_Price':price,'Effective_From':fromd,
             'Effective_To':tod,'Status':'Active'})
    dump(i,'Bridge_Campaign_Product_Group',campaign_bridge)
    dump(i,'Dim_Ad_Campaign',[
        {'Ad_Campaign_ID':f'AD{k}', 'Ad_Campaign_Name':f'Advertising {k}', 'Ad_Type':'Shop Ads',
         'Start_Date':'2026-10-01','End_Date':'2026-11-30'} for k in range(1,4)])
    vouchers=[('V10','Seller 10 percent',.10,250,60),('V15','Selected 15 percent',.15,200,45),('V05','Low cap 5 percent',.05,0,20)]
    dump(i,'Dim_Voucher',[{'Voucher_ID':vid,'Voucher_Name':name,'Discount_Rate':rate,
      'Minimum_Spend_Amount':minimum,'Maximum_Discount_Amount':cap,'Is_Active':True,
      'Effective_From':'2026-10-01','Effective_To':'2026-11-30'} for vid,name,rate,minimum,cap in vouchers])
    elig={'V10':['PG01','PG02','PG03','PG04','PG05'],'V15':['PG01','PG05'],'V05':['PG03']}
    dump(i,'Bridge_Voucher_Product_Group',[{'Voucher_ID':k,'Product_Group_ID':g} for k,gs in elig.items() for g in gs])
    dump(i,'Ref_Affiliate_Commission_Rule',[{'Affiliate_Rule_ID':f'AFF-{g}',
      'Product_Group_ID':g,'Affiliate_Commission_Rate':rate,'Effective_From':'2026-01-01',
      'Effective_To':None,'Is_Active':True} for g,rate in zip([x[0] for x in GROUPS],[.06,.08,.10,.12,.09])])
    dump(i,'Ref_Platform_Fee_Estimate_Rule',[{'Platform_Fee_Rule_ID':f'FEE-{g}',
      'Product_Group_ID':g,'Total_Platform_Fee_Rate':.10,'Fee_Calculation_Mode':'FIXED_TOTAL_RATE',
      'Platform_Commission_Rate':None,'Transaction_Fee_Rate':None,'Commerce_Growth_Fee_Rate':None,
      'Infrastructure_Fee_Per_Order':None,'Effective_From':'2026-01-01','Effective_To':None,
      'Is_Mock_Assumption':True} for g,_,_ in GROUPS])
    dump(i,'Ref_Business_Target',[{'Target_Year_Month':'2026-10','Revenue_Target':110000,
          'Minimum_Profit_Protection_Rate':.10},
          {'Target_Year_Month':'2026-11','Revenue_Target':120000,'Minimum_Profit_Protection_Rate':.10}])
    dump(i,'Ref_Cost_Policy',[{'Cost_Policy_ID':'PLAN-2026','Fixed_Fulfillment_Cost_Per_Order':12,
       'Claim_Risk_Allowance_Rate':.02,'Planning_Base_Cost_Rate':.60,
       'Planning_Adjustable_Gap_Rate':.30,'Effective_From':'2026-01-01',
       'Effective_To':None,'Is_Active':True}])
    # Large fixed-cost receipts: enough stock even for optional performance runs.
    dump(i,'Fact_Goods_Receipt',[{'Goods_Receipt_ID':'GR01','Receipt_Date':'2026-09-29 10:00:00',
       'Supplier_ID':'SUP-MOCK','Reference_PO_ID':'PO-0001','Source_System':'MOCK'}])
    prices={k:round(v*.4,2) for k,_,v in GROUPS}
    dump(i,'Fact_Goods_Receipt_Items',[{'Goods_Receipt_Item_ID':f'G-{s["SKU_ID"]}',
     'Goods_Receipt_ID':'GR01','SKU_ID':s['SKU_ID'],
     'Received_Qty':max(1000, int(n_initial*.5+n_incremental)),
     'Unit_Cost':prices[s['Product_Group_ID']],
     'Total_Cost':prices[s['Product_Group_ID']]*max(1000,int(n_initial*.5+n_incremental)),
     'Remaining_Qty':max(1000,int(n_initial*.5+n_incremental)), 'Lot_No':'LOT-01'} for s in sku])
    skus=[s['SKU_ID'] for s in sku]
    h,it,fl=orders(n_initial,seed,datetime(2026,10,1), 'OCT',skus,[v[0] for v in vouchers])
    dump(i,'Fact_Orders',h);dump(i,'Fact_Order_Items',it);dump(i,'Fact_Internal_Fulfillment',fl)
    h2,it2,fl2=orders(n_incremental,seed+1,datetime(2026,11,1),'NOV',skus,[v[0] for v in vouchers])
    # Promote only previously Pending orders. Never move already-paid October
    # sales into November; that would corrupt the monthly KPI on incremental load.
    pending_october=[order for order in h if order['Current_Status']=='Pending']
    updates=[];extra_fulfill=[]
    for j,orig in enumerate(pending_october[:24]):
        revised=orig.copy();revised['Current_Status']='Paid';revised['Paid_At']=(datetime(2026,11,1,8,0)+timedelta(minutes=j)).isoformat(' ')
        updates.append(revised)
        extra_fulfill.append({'Fulfillment_ID':f'FUL-{orig["Order_ID"]}','Order_ID':orig['Order_ID'],
          'Secondary_Packaging_Cost':3,'Packing_Labor_Cost':5,'Actual_Shipping_Cost':4,
          'Fulfillment_Timestamp':'2026-11-01 12:00:00'})
    # Deliberate backdated changes to simulated paid October fulfillment costs.
    corrections=[]
    for r in fl[:8]:
        r2=r.copy();r2['Packing_Labor_Cost']+=3;r2['Fulfillment_Timestamp']='2026-11-01 13:00:00';corrections.append(r2)
    dump(u,'Fact_Orders',h2+updates);dump(u,'Fact_Order_Items',it2)
    dump(u,'Fact_Internal_Fulfillment',fl2+extra_fulfill+corrections)
    # Ads native daily+group grain, sample/claim events. Never join Ads to each SKU.
    a=[]
    for date in pd.date_range('2026-10-01','2026-10-31'):
        for group,_,_ in GROUPS:
            r=random.Random(f'{seed}-{date.date()}-{group}')
            a.append({'Ad_Record_ID':f'AD-{date:%Y%m%d}-{group}','Record_Date':str(date.date()),
             'Ad_Campaign_ID':f'AD{1+int(group[-1])%3}','Product_Group_ID':group,
             'Ad_Spend_Amount':r.choice([0,3,7,12,18]),'Impressions':r.randint(20,500),
             'Clicks':r.randint(2,25),'Conversions':r.randint(0,8),
             'Reported_Ads_GMV':None,'Reported_Ads_Orders':None,'Reported_Revenue_Basis':None})
    dump(i,'Fact_Marketing_Costs',a)
    a2=[dict(r,Ad_Record_ID=f'AD-20261101-{r["Product_Group_ID"]}',Record_Date='2026-11-01') for r in a[:5]]
    dump(u,'Fact_Marketing_Costs',a2)
    samples=[]
    for n in range(1,12):
        r=random.Random(seed+n)
        samples.append({'Sample_ID':f'SAMP{n:03d}', 'SKU_ID':r.choice(skus),
        'Creator_ID':f'CR{1+n%8:02d}','Sample_Quantity':1,'Request_Date':'2026-10-10 08:00:00',
        'Dispatched_Date':f'2026-10-{10+n%10:02d} 09:00:00',
        'Sample_Shipping_Cost':5,'Sample_COGS':None})
    dump(i,'Fact_Free_Samples',samples)
    dump(u,'Fact_Free_Samples',[{'Sample_ID':'SAMP-NEW-001','SKU_ID':skus[1],
       'Creator_ID':'CR01','Sample_Quantity':1,'Request_Date':'2026-11-01 08:00:00',
       'Dispatched_Date':'2026-11-01 10:00:00','Sample_Shipping_Cost':5,'Sample_COGS':None}])
    paid_by_order={hh['Order_ID']:hh for hh in h}
    paid_items=[x for x in it if paid_by_order[x['Order_ID']]['Current_Status'] in PAID
                and paid_by_order[x['Order_ID']]['Paid_At'][:10]<='2026-10-26']
    claim_hdr=[];claim_dt=[]
    for j,item in enumerate(paid_items[:8]):
        cl=f'CLM{j+1:03d}'
        claim_hdr.append({'Claim_ID':cl,'Claim_Date':'2026-10-27 15:00:00',
              'Claim_Reason':'Simulated damaged item','Claim_Status':'Closed'})
        claim_dt.append({'Claim_Detail_ID':f'{cl}-01','Claim_ID':cl,
            'Order_Item_ID':item['Order_Item_ID'],'Claim_Qty':1,'Replacement_Qty':0,
            'Return_Qty':0,'Disposal_Qty':0,'Backend_Packing_Cost':2,
            'Backend_Shipping_Cost':3,'Replacement_Product_Cost':0,
            'Disposal_Loss_Cost':0,'Backend_Action_Date':'2026-10-29 11:00:00'})
    dump(i,'Fact_Claim_Header',claim_hdr);dump(i,'Fact_Claim_Details',claim_dt)
    # Explicit validation metadata; generator never claims these are observed TikTok records.
    (base/'README.md').write_text('# SYNTHETIC SOURCE DATA\nEntirely generated for educational demo. No actual TikTok API, customer or billing records.\n'
      f'Random seed: {seed}; initial orders: {n_initial}; incremental new orders: {n_incremental}.\n'
      f'Run 2 includes {len(updates)} October pending->November paid transitions and {len(corrections)} October fulfillment revisions.\n'
      'ER1 price, discounts, COGS and commission are derived by ingestion and intentionally blank in item CSVs.\n',encoding='utf-8')
    return {'initial_orders':n_initial,'incremental_new_orders':n_incremental,'pending_to_paid':len(updates),'late_fulfillment_updates':len(corrections)}

if __name__=='__main__':
    print(generate())
