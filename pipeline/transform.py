"""ER1 Raw -> governed, item-grain ER2 staging Parquet. Changed facts only; master lookups complete."""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime,timedelta,date
from collections import defaultdict
import pandas as pd
from .er1 import PipelineError,money,PAID

NA_VOUCHER={'Voucher_Key':0,'Voucher_ID':'NA','Voucher_Name':'Not Applicable',
 'Discount_Rate':0.,'Minimum_Spend_Amount':0.,'Maximum_Discount_Amount':None,
 'Voucher_Active':True,'Voucher_Start_Date':None,'Voucher_End_Date':None}

def blank(v):return v is None or (isinstance(v,float) and pd.isna(v))
def safe(v,default=0):return default if blank(v) else v

def load_raw(raw,name):
    file=raw/f'{name}.parquet'
    if not file.exists():raise PipelineError('T04_MISSING_RAW',str(file))
    return pd.read_parquet(file,engine='pyarrow').where(lambda d:pd.notna(d),None).to_dict('records')

def save_std(std,name,rows,cols=None):
    df=pd.DataFrame(rows,columns=cols if cols else None)
    if df.empty and cols is None:df=pd.DataFrame({'__empty__':[]})
    df.to_parquet(std/f'{name}.parquet',index=False,engine='pyarrow')
    return len(df)

def dim_date_rows():
    cur=date(2026,10,1);end=date(2026,11,30);out=[]
    while cur<=end:
        out.append({'Date_Key':int(cur.strftime('%Y%m%d')),'Full_Date':str(cur),
          'Day_Number':cur.day,'Day_Name':cur.strftime('%A'),
          'Week_Start_Date':str(cur-timedelta(days=cur.weekday())),
          'Month_Number':cur.month,'Month_Name':cur.strftime('%B'),
          'Year_Month':cur.strftime('%Y-%m'),'Quarter_Number':((cur.month-1)//3)+1,
          'Year_Number':cur.year,'Is_Month_Start':cur.day==1})
        cur+=timedelta(days=1)
    return out

def transform(lake_dir:Path,control_dir:Path,batch:str,inject_error=None):
    raw=lake_dir/'raw'/batch;std=lake_dir/'standardized'/batch;std.mkdir(parents=True,exist_ok=True)
    changes=json.loads((control_dir/f'changes_{batch}.json').read_text(encoding='utf-8'))
    groups=load_raw(raw,'Dim_Product_Group');skus=load_raw(raw,'Dim_SKU')
    creators=load_raw(raw,'Dim_Creator');vouchers=load_raw(raw,'Dim_Voucher')
    ad_campaigns=load_raw(raw,'Dim_Ad_Campaign');orders=load_raw(raw,'Fact_Orders')
    items=load_raw(raw,'Fact_Order_Items');fulfill=load_raw(raw,'Fact_Internal_Fulfillment')
    ads=load_raw(raw,'Fact_Marketing_Costs');samples=load_raw(raw,'Fact_Free_Samples')
    claims=load_raw(raw,'Fact_Claim_Details');cb=load_raw(raw,'Bridge_Campaign_Product_Group')
    policy=load_raw(raw,'Ref_Platform_Fee_Estimate_Rule');targets=load_raw(raw,'Ref_Business_Target')
    campaigns=load_raw(raw,'Dim_Campaign')
    pgroup={r['Product_Group_ID']:r for r in groups};sku={r['SKU_ID']:r for r in skus}
    creator={r['Creator_ID']:j for j,r in enumerate(sorted(creators,key=lambda x:x['Creator_ID']),1)}
    voucher={r['Voucher_ID']:j for j,r in enumerate(sorted(vouchers,key=lambda x:x['Voucher_ID']),1)}
    acampaign={r['Ad_Campaign_ID']:j for j,r in enumerate(sorted(ad_campaigns,key=lambda x:x['Ad_Campaign_ID']),1)}
    product={r['SKU_ID']:j for j,r in enumerate(sorted(skus,key=lambda x:x['SKU_ID']),1)}
    od={r['Order_ID']:r for r in orders};fm={r['Order_ID']:r for r in fulfill}
    campaigns_dict={r['Campaign_ID']:r for r in campaigns}
    fee_rules={r['Product_Group_ID']:r for r in policy}
    columns={}
    from .schema import columns_for
    for name in ['Dim_Date','Dim_Product','Dim_Creator','Dim_Ad_Campaign','Dim_Voucher','Dim_Cost_Basis',
                 'Fact_Sales_Order_Item','Fact_Ads_Daily','Fact_Free_Sample','Fact_Business_Target_Monthly']:
        columns[name]=columns_for(name,'er2')
    # Check actual master rules and overlap (T02), not just injected error.
    if inject_error=='T02':cb=cb+[dict(cb[0],Enrollment_ID='INJECTED_OVERLAP',Campaign_ID='TEST')]
    for a in cb:
        for b in cb:
            if a['Enrollment_ID']<b['Enrollment_ID'] and a['Product_Group_ID']==b['Product_Group_ID'] and \
               a['Status']=='Active' and b['Status']=='Active' and \
               a['Effective_From']<=b['Effective_To'] and b['Effective_From']<=a['Effective_To']:
                raise PipelineError('T02_CAMPAIGN_OVERLAP',f"{a['Product_Group_ID']} campaigns overlap")
    dims={
      'Dim_Date':dim_date_rows(),
      'Dim_Product':[{'Product_Key':product[s['SKU_ID']],'SKU_ID':s['SKU_ID'],'SKU_Name':s['SKU_Name'],
         'Color':s['Color'],'Size':s['Size'],'Product_Group_ID':s['Product_Group_ID'],
         'Product_Group_Name':pgroup[s['Product_Group_ID']]['Product_Group_Name'],
         'Base_Selling_Price':pgroup[s['Product_Group_ID']]['Base_Selling_Price'],
         'Standard_Product_Cost':pgroup[s['Product_Group_ID']]['Cost_Standard_Product'],
         'Product_Group_Status':pgroup[s['Product_Group_ID']]['Status'],'Product_Status':s['Status'],
         'Effective_From':'2026-01-01','Effective_To':None,'Is_Current':True} for s in skus],
      'Dim_Creator':[{'Creator_Key':0,'Creator_ID':'NA','Creator_Name':'Not Applicable',
         'Creator_Type':'NA','Creator_Status':'Active'}]+[
         {'Creator_Key':creator[x['Creator_ID']],'Creator_ID':x['Creator_ID'],
          'Creator_Name':x['Creator_Name'],'Creator_Type':x['Creator_Type'],
          'Creator_Status':x['Status']} for x in creators],
      'Dim_Ad_Campaign':[{'Ad_Campaign_Key':acampaign[x['Ad_Campaign_ID']],
       'Ad_Campaign_ID':x['Ad_Campaign_ID'],'Ad_Campaign_Name':x['Ad_Campaign_Name'],
       'Ad_Type':x['Ad_Type'],'Campaign_Start_Date':x['Start_Date'],
       'Campaign_End_Date':x['End_Date']} for x in ad_campaigns],
      'Dim_Voucher':[NA_VOUCHER]+[{'Voucher_Key':voucher[x['Voucher_ID']],
       'Voucher_ID':x['Voucher_ID'],'Voucher_Name':x['Voucher_Name'],
       'Discount_Rate':x['Discount_Rate'],'Minimum_Spend_Amount':x['Minimum_Spend_Amount'],
       'Maximum_Discount_Amount':x['Maximum_Discount_Amount'],'Voucher_Active':x['Is_Active'],
       'Voucher_Start_Date':x['Effective_From'],'Voucher_End_Date':x['Effective_To']} for x in vouchers],
      'Dim_Cost_Basis':[{'Cost_Basis_Key':1,'Platform_Fee_Basis':'ESTIMATED_10PCT',
         'Fulfillment_Basis':'MOCK_ACTUAL'},
        {'Cost_Basis_Key':2,'Platform_Fee_Basis':'ESTIMATED_10PCT','Fulfillment_Basis':'UNKNOWN'}]
    }
    results={}
    for name,rows in dims.items():results[name]=save_std(std,name,rows,columns[name])
    g=dict((x['Product_Group_ID'],x) for x in groups)
    changed=set(changes['changed_order_item_ids']);by_order=defaultdict(list)
    for r in items:
        if r['Order_ID'] in od and od[r['Order_ID']]['Current_Status'] in PAID:
            by_order[r['Order_ID']].append(r)
    sales=[];lineage=[];dirty=set()
    for oid,order_lines in by_order.items():
        o=od[oid]
        # Order cost allocated pro rata by item Net Revenue; last line corrects rounding residue.
        fl=fm.get(oid)
        total_fl=sum(float(safe(fl[k])) for k in ('Secondary_Packaging_Cost','Packing_Labor_Cost','Actual_Shipping_Cost')) if fl else 0
        eligible_net=sum(float(x['Total_Selling_Amount'])-float(safe(x['Voucher_Allocated_Amount'])) for x in order_lines)
        outstanding=money(total_fl)
        for idx,x in enumerate(sorted(order_lines,key=lambda x:x['Order_Item_ID'])):
            itemid=x['Order_Item_ID'];group=sku[x['SKU_ID']]['Product_Group_ID']
            amt=money(float(x['Total_Selling_Amount'])-float(safe(x['Voucher_Allocated_Amount'])))
            ft=money(outstanding if idx==len(order_lines)-1 else total_fl*amt/eligible_net) if fl else 0
            if fl:outstanding=money(outstanding-ft)
            if itemid not in changed:continue
            if inject_error=='T01' and not sales:
                voucher_amt=float(x['Total_Selling_Amount'])+1
            else:voucher_amt=float(safe(x['Voucher_Allocated_Amount']))
            if voucher_amt<0 or voucher_amt>float(x['Total_Selling_Amount']):
                raise PipelineError('T01_VOUCHER',f'{itemid}: allocated {voucher_amt}, sales {x["Total_Selling_Amount"]}')
            rate=fee_rules[group]
            if rate['Fee_Calculation_Mode']!='FIXED_TOTAL_RATE' or abs(float(rate['Total_Platform_Fee_Rate'])-.10)>0.0001:
                raise PipelineError('T05_FEE_POLICY',f'{group} not fixed 10 percent')
            net=money(float(x['Total_Selling_Amount'])-voucher_amt)
            cost=money(float(safe(x['Total_COGS'])))
            if cost<=0:raise PipelineError('T06_MISSING_COGS',itemid)
            affiliate=money(float(safe(x['Fee_Affiliate_Payout'])))
            if x['Creator_ID'] is None and affiliate!=0:raise PipelineError('T06_AFFILIATE_WITHOUT_CREATOR',itemid)
            fee=money(net*float(rate['Total_Platform_Fee_Rate']))
            c=campaigns_dict.get(x['Campaign_ID']) if not blank(x['Campaign_ID']) else None
            date_key=int(o['Paid_At'][:10].replace('-',''))
            row={'Sales_Fact_Key':None,'Sales_Date_Key':date_key,
              'Product_Key':product[x['SKU_ID']],'Creator_Key':creator.get(x['Creator_ID'],0),
              'Voucher_Key':voucher.get(o['Voucher_ID'],0) if voucher_amt>0 else 0,
              'Cost_Basis_Key':1 if fl else 2,
              'Campaign_ID':x['Campaign_ID'],'Campaign_Name':c['Campaign_Name'] if c else None,
              'Campaign_Type':c['Campaign_Type'] if c else None,
              'Source_Order_ID':oid,'Source_Order_Item_ID':itemid,
              'Quantity':int(x['Quantity']),'Base_Unit_Price_At_Sale':float(x['Base_Unit_Price_At_Sale']),
              'Campaign_Unit_Price_At_Sale':float(x['Unit_Selling_Price']),
              'Gross_Reference_Sales':money(float(x['Base_Unit_Price_At_Sale'])*x['Quantity']),
              'Campaign_Price_Reduction':money(float(safe(x['Campaign_Discount_Amount']))),
              'Sales_After_Campaign':float(x['Total_Selling_Amount']),
              'Voucher_Allocated':voucher_amt,'Net_Revenue':net,'COGS':cost,
              'Platform_Fee_Cost':fee,'Fulfillment_Cost':ft,'Affiliate_Cost':affiliate,
              'Sales_Contribution_Pre_Ads_Sample_Claim':money(net-cost-fee-ft-affiliate)}
            sales.append(row);dirty.add((date_key,group))
            lineage.append({'Source_Order_Item_ID':itemid,'Source_Order_ID':oid,'Batch_ID':batch,
               'Source_File':'Fact_Order_Items.csv','ER1_Table':'Fact_Order_Items',
               'Raw_Parquet':'Fact_Order_Items.parquet',
               'Standardized_Parquet':'Fact_Sales_Order_Item.parquet',
               'ER2_Fact':'Fact_Sales_Order_Item',
               'Sales_Date_Key':date_key,'Product_Group_ID':group,
               'Gross_Reference_Sales':row['Gross_Reference_Sales'],'Net_Revenue':net,
               'COGS':cost,'Affiliate_Cost':affiliate})
    # Assign stable surrogate Sales_Fact_Key via Order Item business key, preserving it across batch reloads.
    # This id is allocated at DuckDB load for first appearance, never stored in standardized parquet.
    results['Fact_Sales_Order_Item']=save_std(std,'Fact_Sales_Order_Item',sales,columns['Fact_Sales_Order_Item'])
    adrows=[]
    for x in ads:
        if x['Ad_Record_ID'] not in set(changes['changed_ad_ids']):continue
        if x['Product_Group_ID'] not in g:raise PipelineError('T07_UNKNOWN_GROUP',x['Product_Group_ID'])
        date_key=int(x['Record_Date'].replace('-',''))
        adrows.append({'Ads_Fact_Key':None,'Date_Key':date_key,
         'Product_Group_ID':x['Product_Group_ID'],'Ad_Campaign_Key':acampaign[x['Ad_Campaign_ID']],
         'Source_Ad_Record_ID':x['Ad_Record_ID'],'Ads_Spend':x['Ad_Spend_Amount'],
         'Impressions':x['Impressions'],'Clicks':x['Clicks'],'Conversions':x['Conversions'],
         'Reported_Ads_GMV':x['Reported_Ads_GMV'],'Reported_Ads_Orders':x['Reported_Ads_Orders'],
         'Reported_Revenue_Basis':x['Reported_Revenue_Basis']})
        dirty.add((date_key,x['Product_Group_ID']))
    results['Fact_Ads_Daily']=save_std(std,'Fact_Ads_Daily',adrows,columns['Fact_Ads_Daily'])
    samrows=[]
    for x in samples:
        if x['Sample_ID'] not in set(changes['changed_sample_ids']):continue
        group=sku[x['SKU_ID']]['Product_Group_ID'];date_key=int(x['Dispatched_Date'][:10].replace('-',''))
        samrows.append({'Sample_Fact_Key':None,'Dispatched_Date_Key':date_key,
          'Product_Key':product[x['SKU_ID']],'Creator_Key':creator[x['Creator_ID']],
          'Source_Sample_ID':x['Sample_ID'],'Sample_Quantity':int(x['Sample_Quantity']),
          'Sample_COGS':float(x['Sample_COGS']),'Sample_Shipping_Cost':float(x['Sample_Shipping_Cost']),
          'Total_Sample_Cost':money(float(x['Sample_COGS'])+float(x['Sample_Shipping_Cost']))})
        dirty.add((date_key,group))
    results['Fact_Free_Sample']=save_std(std,'Fact_Free_Sample',samrows,columns['Fact_Free_Sample'])
    trows=[{'Target_Fact_Key':k,'Month_Start_Date_Key':int(x['Target_Year_Month'].replace('-','')+'01'),
      'Target_Year_Month':x['Target_Year_Month'],'Revenue_Target':x['Revenue_Target'],
      'Minimum_Profit_Protection_Rate':x['Minimum_Profit_Protection_Rate']} for k,x in enumerate(sorted(targets,key=lambda x:x['Target_Year_Month']),1)]
    results['Fact_Business_Target_Monthly']=save_std(std,'Fact_Business_Target_Monthly',trows,columns['Fact_Business_Target_Monthly'])
    # Claim cost stays in governed external staging, not a fifth ER2 Fact.
    lookup_items={x['Order_Item_ID']:x for x in items};claim_daily=defaultdict(float)
    for c in claims:
        x=lookup_items[c['Order_Item_ID']];group=sku[x['SKU_ID']]['Product_Group_ID']
        day=int(c['Backend_Action_Date'][:10].replace('-',''))
        val=sum(float(safe(c[k])) for k in ('Backend_Packing_Cost','Backend_Shipping_Cost','Replacement_Product_Cost','Disposal_Loss_Cost'))
        claim_daily[(day,group)]+=val
        dirty.add((day,group))
    cdrows=[{'Date_Key':d,'Product_Group_ID':g,'Claim_Cost':money(val)} for (d,g),val in sorted(claim_daily.items())]
    save_std(std,'claim_daily_external',cdrows,['Date_Key','Product_Group_ID','Claim_Cost'])
    (std/'dirty_dates_groups.json').write_text(json.dumps([{'Date_Key':d,'Product_Group_ID':g} for d,g in sorted(dirty)],indent=2),encoding='utf-8')
    (std/'lineage.csv').write_text(pd.DataFrame(lineage).to_csv(index=False),encoding='utf-8')
    (control_dir/f'allocation_audit_{batch}.json').write_text(json.dumps({
        'batch':batch,'voucher':'eligible post-campaign prorated, cent balancing at order',
        'platform':'10% of item Net Revenue',
        'affiliate':'rate by Product Group x item Net Revenue',
        'fulfillment':'order simulated actual cost prorated by item Net Revenue, last cent adjusted',
        'sales_at':'Paid_At','price_locked_at':'Order_Created_At',
        'ads':'native date/group, never joined directly to SKU sales',
        'changed_sales':len(sales),'dirty_groups_dates':len(dirty)},indent=2),encoding='utf-8')
    return {'standardized_tables':len(results)+1,'changed_sales':len(sales),
      'changed_ads':len(adrows),'changed_samples':len(samrows),'dirty_groups_dates':len(dirty)}
