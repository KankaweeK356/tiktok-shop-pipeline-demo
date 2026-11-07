"""Generate inspectable schema-field mapping docs from the actual ER V3/V5 DBML."""
from pathlib import Path
import csv,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from pipeline.schema import parse_dbml
TGT={
'Dim_Date':('ER1 Fact_Orders.Paid_At / other event dates','Calendar YYYYMMDD for Oct-Nov 2026; dates/quarter/ISO week derived; month target first-of-month'),
'Dim_Product':('ER1 Dim_SKU + Dim_Product_Group','SKU version, deterministic Product_Key; flatten PG; cost 40% of base price'),
'Dim_Creator':('ER1 Dim_Creator','Creator dimension; Creator_Key=0 Not Applicable'),
'Dim_Ad_Campaign':('ER1 Dim_Ad_Campaign','Ad campaign master, not sales campaign'),
'Dim_Voucher':('ER1 Dim_Voucher','Percentage rate, minimum spend and cap; Voucher_Key=0 Not Applicable'),
'Dim_Cost_Basis':('ER1 Ref_Platform_Fee_Estimate_Rule + Fact_Internal_Fulfillment','Fixed ESTIMATED_10PCT; fulfillment MOCK_ACTUAL / UNKNOWN'),
'Fact_Sales_Order_Item':('ER1 Fact_Order_Items + Fact_Orders + Fact_Internal_Fulfillment + Dim_SKU + Campaign','Paid item grain; upsert Source_Order_Item_ID; paid date; allocated costs and discounts'),
'Fact_Ads_Daily':('ER1 Fact_Marketing_Costs','Date x Ads Campaign x Product Group, not SKU joins'),
'Fact_Free_Sample':('ER1 Fact_Free_Samples + Dim_SKU','Dispatch date x SKU x creator, separate from order sales'),
'Fact_Business_Target_Monthly':('ER1 Ref_Business_Target','One store-month target, never replicate by group/day'),
'Mart_Product_Group_Daily_Performance':('ER2 Sales/Ads/Sample + ER1 Fact_Claim_Details','Separate group/date aggregations, combine without fan-out, affected date-group recomputation'),
'View_Shop_Monthly_KPI':('ER2 daily Mart + Fact_Business_Target_Monthly','SQL View, monthly rollup BEFORE one-month target join; 10% of full-price Gross_Reference_Sales')}
SPEC={
 'Fact_Sales_Order_Item':{
 'Sales_Date_Key':'Fact_Orders.Paid_At -> YYYYMMDD, Paid non-cancelled',
 'Product_Key':'Fact_Order_Items.SKU_ID -> Dim_Product as-of Order_Created_At',
 'Creator_Key':'Fact_Order_Items.Creator_ID -> Dim_Creator; 0 for none',
 'Voucher_Key':'Fact_Orders.Voucher_ID for eligible item with allocated voucher, else 0',
 'Cost_Basis_Key':'ESTIMATED_10PCT+MOCK_ACTUAL or UNKNOWN based on fulfillment existence',
 'Campaign_ID':'Fact_Order_Items.Campaign_ID locked at order creation',
 'Campaign_Name':'Dim_Campaign.Campaign_Name joined by Campaign_ID',
 'Campaign_Type':'Dim_Campaign.Campaign_Type joined by Campaign_ID',
 'Source_Order_ID':'Fact_Order_Items.Order_ID','Source_Order_Item_ID':'Fact_Order_Items.Order_Item_ID',
 'Quantity':'Fact_Order_Items.Quantity','Base_Unit_Price_At_Sale':'Fact_Order_Items.Base_Unit_Price_At_Sale',
 'Campaign_Unit_Price_At_Sale':'Fact_Order_Items.Unit_Selling_Price',
 'Gross_Reference_Sales':'Quantity * Base_Unit_Price_At_Sale',
 'Campaign_Price_Reduction':'Fact_Order_Items.Campaign_Discount_Amount',
 'Sales_After_Campaign':'Fact_Order_Items.Total_Selling_Amount',
 'Voucher_Allocated':'Fact_Order_Items.Voucher_Allocated_Amount',
 'Net_Revenue':'Sales_After_Campaign - Voucher_Allocated (shipping excluded)',
 'COGS':'Fact_Order_Items.Total_COGS, reconciled to FIFO',
 'Platform_Fee_Cost':'ROUND(0.10 x Net_Revenue, 2) simulated fee',
 'Fulfillment_Cost':'Pro-rata Fact_Internal_Fulfillment packaging+labor+shipping allocated to item net, reconcile cents',
 'Affiliate_Cost':'Fact_Order_Items.Fee_Affiliate_Payout = group rate x item net',
 'Sales_Contribution_Pre_Ads_Sample_Claim':'Net Revenue - COGS - Platform - Fulfillment - Affiliate',
 'Sales_Fact_Key':'Stable surrogate allocated during Warehouse first insert, retained on upsert'},
 'Mart_Product_Group_Daily_Performance':{
 'Gross_Reference_Sales':'SUM Sales Fact Gross by Paid Date+PG',
 'Campaign_Price_Reduction':'SUM Sales Fact Campaign reduction by Paid Date+PG',
 'Voucher_Discount':'SUM Sales Fact Voucher_Allocated by Paid Date+PG',
 'Net_Revenue':'SUM Sales Fact Net by Paid Date+PG',
 'COGS':'SUM Sales Fact COGS','Platform_Fee_Cost':'SUM Sales Fact Platform_Fee_Cost',
 'Fulfillment_Cost':'SUM Sales Fact Fulfillment_Cost',
 'Affiliate_Cost':'SUM Sales Fact Affiliate_Cost',
 'Ads_Cost':'SUM Fact_Ads_Daily Ads_Spend by Date+PG (never join to SKU)',
 'Sample_Cost':'SUM Fact_Free_Sample Total_Sample_Cost by Dispatched Date+PG',
 'Claim_Cost':'SUM ER1 Fact_Claim_Details costs by Backend_Action_Date+PG via external standardized claim ledger',
 'Contribution_Profit':'Net - COGS - Platform - Fulfillment - Affiliate - Ads - Sample - Claim; NULL if incomplete',
 'Data_Cost_Basis':'INCOMPLETE if any UNKNOWN fulfillment; else MOCK_ACTUAL_WITH_POLICY_FEE',
 'Calculated_At':'timestamp of mart row rebuild'},
 'View_Shop_Monthly_KPI':{
 'Gross_Reference_Sales':'SUM Mart Gross_Reference_Sales by Year_Month',
 'Net_Revenue':'SUM Mart Net_Revenue by Year_Month',
 'Contribution_Profit':'SUM Mart Profit, NULL if incomplete month',
 'Profit_Protection_Required':'Gross_Reference_Sales x Minimum_Profit_Protection_Rate',
 'Profit_Protection_Headroom':'Contribution_Profit - Profit_Protection_Required',
 'Profit_Protection_Status':'PASS if Profit>=Required else FAIL; handle incomplete/missing/zero policy',
 'Profit_Margin_Pct':'100 x Profit / Net_Revenue (descriptive not gate)',
 'Profit_Protection_Rate_Pct':'100 x Profit / Gross_Reference_Sales',
 'Profit_Protection_Gap_Pp':'100 x (Profit/Gross - policy rate)',
 'Revenue_Achievement_Pct':'100 x Revenue / Revenue_Target if target>0',
 'Revenue_Gap':'Net_Revenue - Revenue_Target',
 'Year_Month':'Dim_Date.Year_Month group via Mart.Date_Key',
 'Month_Start_Date_Key':'Monthly target first-of-month Date_Key',
 'Minimum_Profit_Protection_Rate':'Fact_Business_Target_Monthly.Minimum_Profit_Protection_Rate',
 'Revenue_Target':'Fact_Business_Target_Monthly.Revenue_Target',
 'Profit_Data_Status':'COMPLETE / INCOMPLETE from constituent Mart rows',
 'Target_Status':'OK / ZERO_TARGET / MISSING_TARGET / INVALID_TARGET'}
}
for table,dbml in [('ER1','ER1_V3.dbml'),('ER2','ER2_V5.dbml')]:
    ts,refs=parse_dbml(ROOT/'schemas'/dbml)
    with open(ROOT/'docs'/f'{table}_Data_Dictionary.csv','w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['Table','Field','Data_Type','Primary_Key','Required','Unique'])
        for t in ts:
            for c in t.columns:w.writerow([t.name,c.name,c.typ,c.name in t.pk,c.not_null,c.unique])
with open(ROOT/'docs'/'ER2_Source_to_Target_Mapping.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f);w.writerow(['Target_Table','Target_Field','Source_Tables','Transformation_Rule','Data_Grain_And_Load'])
    ts,_=parse_dbml(ROOT/'schemas/ER2_V5.dbml')
    for t in ts:
        src,default=TGT[t.name]
        for c in t.columns:
            detail=SPEC.get(t.name,{}).get(c.name,default)
            w.writerow([t.name,c.name,src,detail,
                'logical SQL view' if t.name.startswith('View_') else 'source-grain / delta upsert' if t.name.startswith('Fact_') else 'affected Date x Product Group' if t.name.startswith('Mart_') else 'small master dimension full upsert'])
print('Schema dictionaries and ER2 field mapping generated.')
