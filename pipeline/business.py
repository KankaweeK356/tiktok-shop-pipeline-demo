"""Inspectable, non-mutating Product Group profitability and affiliate what-if headroom."""
from pathlib import Path
import pandas as pd

def business_report(db:Path,output_dir:Path):
    import duckdb
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect(str(db),read_only=True)
    try:
        monthly=con.execute('SELECT * FROM View_Shop_Monthly_KPI ORDER BY Year_Month').df()
        monthly.to_csv(output_dir/'monthly_kpi.csv',index=False)
        # Count affiliate sales at row-grain and subtract non-affiliate costs in a safe group rollup.
        sales=con.execute('''SELECT p.Product_Group_ID,p.Product_Group_Name,
            SUM(CASE WHEN s.Creator_Key<>0 THEN s.Net_Revenue ELSE 0 END) Affiliate_Eligible_Net_Revenue
            FROM Fact_Sales_Order_Item s JOIN Dim_Product p ON p.Product_Key=s.Product_Key
            GROUP BY p.Product_Group_ID,p.Product_Group_Name''').df()
        group=con.execute('''SELECT Product_Group_ID,MAX(Product_Group_Name) Product_Group_Name,
          SUM(Gross_Reference_Sales) Gross_Reference_Sales,
          SUM(Net_Revenue) Net_Revenue,SUM(COALESCE(Contribution_Profit,0)) Contribution_Profit,
          SUM(Affiliate_Cost) Affiliate_Cost,
          MAX(CASE WHEN Data_Cost_Basis='INCOMPLETE' THEN 1 ELSE 0 END) Incomplete
          FROM Mart_Product_Group_Daily_Performance GROUP BY Product_Group_ID''').df()
        df=group.merge(sales[['Product_Group_ID','Affiliate_Eligible_Net_Revenue']],on='Product_Group_ID',how='left')
        for col in ['Gross_Reference_Sales','Net_Revenue','Contribution_Profit','Affiliate_Cost','Affiliate_Eligible_Net_Revenue']:
            df[col]=pd.to_numeric(df[col],errors='coerce')
        df['Affiliate_Eligible_Net_Revenue']=df['Affiliate_Eligible_Net_Revenue'].fillna(0)
        df['Minimum_Profit_Amount']=df['Gross_Reference_Sales']*.10
        df['Profit_Excluding_Affiliate']=df['Contribution_Profit']+df['Affiliate_Cost']
        df['Maximum_Affiliate_Cost_Allowed']=df['Profit_Excluding_Affiliate']-df['Minimum_Profit_Amount']
        import numpy as np
        df['Max_Commission_Rate_If_All_Else_Fixed'] = np.where(df['Affiliate_Eligible_Net_Revenue']>0,
            np.clip(df['Maximum_Affiliate_Cost_Allowed']/df['Affiliate_Eligible_Net_Revenue'],0,1),np.nan)
        df.loc[df['Maximum_Affiliate_Cost_Allowed']<0,'Max_Commission_Rate_If_All_Else_Fixed']=float('nan')
        df.loc[df['Incomplete']>0,'Max_Commission_Rate_If_All_Else_Fixed']=float('nan')
        # This is a ceiling on existing affiliate-eligible orders assuming NO change in sales demand.
        df['Assumption']='Existing demand, discounts, other costs remain fixed; rate is not demand-optimal'
        df.to_csv(output_dir/'product_group_affiliate_scenario.csv',index=False)
        return monthly,df
    finally:con.close()
