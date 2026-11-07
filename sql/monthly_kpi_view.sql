-- TikTok Shop ER2 V5 — executable DuckDB SQL, not part of the physical star schema table count.
-- Must run AFTER Dim_Date, Mart_Product_Group_Daily_Performance and Fact_Business_Target_Monthly exist.
-- Every financial measure belongs to a single mock Non-Mall shop; Year_Month is YYYY-MM.
-- Query strategy: monthly group-level mart rollup FIRST, then 1:1 join monthly target.
-- Never join raw SKU-level Sales with group-grain Ads/Samples/Claim.
CREATE OR REPLACE VIEW "View_Shop_Monthly_KPI" AS
WITH monthly_actual_rollup AS (
    SELECT
        d."Year_Month" AS "Year_Month",
        SUM(COALESCE(m."Gross_Reference_Sales", 0)) AS "Gross_Reference_Sales",
        SUM(COALESCE(m."Net_Revenue", 0)) AS "Net_Revenue",
        SUM(COALESCE(m."Contribution_Profit", 0)) AS "Profit_Amount_Sum",
        SUM(CASE WHEN m."Data_Cost_Basis" = 'INCOMPLETE'
                   OR m."Contribution_Profit" IS NULL THEN 1 ELSE 0 END) AS "Incomplete_Rows"
    FROM "Mart_Product_Group_Daily_Performance" AS m
    JOIN "Dim_Date" AS d ON d."Date_Key" = m."Date_Key"
    GROUP BY d."Year_Month"
),
monthly_actual AS (
    SELECT
        "Year_Month", "Gross_Reference_Sales", "Net_Revenue",
        CASE WHEN "Incomplete_Rows" > 0 THEN NULL ELSE "Profit_Amount_Sum" END AS "Contribution_Profit",
        CASE WHEN "Incomplete_Rows" > 0 THEN 'INCOMPLETE' ELSE 'COMPLETE' END AS "Profit_Data_Status"
    FROM monthly_actual_rollup
),
monthly_aligned AS (
    SELECT
        COALESCE(a."Year_Month", t."Target_Year_Month") AS "Year_Month",
        t."Month_Start_Date_Key" AS "Month_Start_Date_Key",
        COALESCE(a."Gross_Reference_Sales", 0) AS "Gross_Reference_Sales",
        COALESCE(a."Net_Revenue", 0) AS "Net_Revenue",
        CASE WHEN a."Year_Month" IS NULL THEN 0 ELSE a."Contribution_Profit" END AS "Contribution_Profit",
        t."Revenue_Target" AS "Revenue_Target",
        t."Minimum_Profit_Protection_Rate" AS "Minimum_Profit_Protection_Rate",
        COALESCE(a."Profit_Data_Status", 'COMPLETE') AS "Profit_Data_Status",
        CASE
          WHEN t."Target_Fact_Key" IS NULL THEN 'MISSING_TARGET'
          WHEN t."Revenue_Target" < 0 THEN 'INVALID_TARGET'
          WHEN t."Revenue_Target" = 0 THEN 'ZERO_TARGET'
          ELSE 'OK'
        END AS "Target_Status"
    FROM monthly_actual AS a
    FULL OUTER JOIN "Fact_Business_Target_Monthly" AS t
      ON a."Year_Month" = t."Target_Year_Month"
)
SELECT
    j."Year_Month",
    j."Month_Start_Date_Key",
    j."Gross_Reference_Sales",
    j."Net_Revenue",
    j."Contribution_Profit",
    j."Revenue_Target",
    j."Minimum_Profit_Protection_Rate",
    CASE WHEN j."Revenue_Target" IS NOT NULL THEN j."Net_Revenue" - j."Revenue_Target" END AS "Revenue_Gap",
    CASE WHEN j."Revenue_Target" > 0 THEN ROUND(100.0 * j."Net_Revenue" / j."Revenue_Target", 2) END AS "Revenue_Achievement_Pct",
    CASE WHEN j."Net_Revenue" > 0 AND j."Contribution_Profit" IS NOT NULL
         THEN ROUND(100.0 * j."Contribution_Profit" / j."Net_Revenue", 2) END AS "Profit_Margin_Pct",
    CASE WHEN j."Minimum_Profit_Protection_Rate" BETWEEN 0 AND 1
         THEN ROUND(j."Gross_Reference_Sales" * j."Minimum_Profit_Protection_Rate", 2) END AS "Profit_Protection_Required",
    CASE WHEN j."Gross_Reference_Sales" > 0 AND j."Contribution_Profit" IS NOT NULL
         THEN ROUND(100.0 * j."Contribution_Profit" / j."Gross_Reference_Sales", 2) END AS "Profit_Protection_Rate_Pct",
    CASE WHEN j."Gross_Reference_Sales" > 0 AND j."Contribution_Profit" IS NOT NULL
           AND j."Minimum_Profit_Protection_Rate" BETWEEN 0 AND 1
         THEN ROUND(100.0 * j."Contribution_Profit" / j."Gross_Reference_Sales"
                    - 100.0 * j."Minimum_Profit_Protection_Rate", 2) END AS "Profit_Protection_Gap_Pp",
    CASE WHEN j."Contribution_Profit" IS NOT NULL
           AND j."Minimum_Profit_Protection_Rate" BETWEEN 0 AND 1
         THEN ROUND(j."Contribution_Profit" - j."Gross_Reference_Sales" * j."Minimum_Profit_Protection_Rate", 2)
    END AS "Profit_Protection_Headroom",
    CASE
      WHEN j."Profit_Data_Status" = 'INCOMPLETE' THEN 'INCOMPLETE_COST'
      WHEN j."Minimum_Profit_Protection_Rate" IS NULL THEN 'MISSING_POLICY'
      WHEN j."Minimum_Profit_Protection_Rate" NOT BETWEEN 0 AND 1 THEN 'INVALID_POLICY'
      WHEN j."Gross_Reference_Sales" <= 0 THEN 'NO_REFERENCE_SALES'
      WHEN j."Contribution_Profit" >= j."Gross_Reference_Sales" * j."Minimum_Profit_Protection_Rate" THEN 'PASS'
      ELSE 'FAIL'
    END AS "Profit_Protection_Status",
    j."Profit_Data_Status",
    j."Target_Status"
FROM monthly_aligned AS j;

-- Key checks:
-- 1) Month 1 source gross 199, profit 25 => Required 19.90, Headroom 5.10, PASS.
-- 2) Old, incorrect gate from V4 (10% of Net_Revenue) must never be used.
-- 3) MONTH with Ads/Claim costs but zero paid sales => NO_REFERENCE_SALES.
-- 4) Missing cost => INCOMPLETE_COST; Profit NULL, but Net Revenue still visible.
-- 5) Target-only month still appears due to FULL OUTER JOIN.
-- 6) Do not compare statuses to results of real TikTok billing or accounting.
