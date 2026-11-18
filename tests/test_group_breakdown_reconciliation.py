"""Per-group cost roll-up must reconcile to the shop-month totals and never turn an unknown cost into zero."""
import duckdb

from pipeline.ci_lab_batch import GROUPS_SQL

COSTS = ["Net_Revenue", "Gross_Reference_Sales", "Ads_Cost", "Campaign_Price_Reduction", "Voucher_Discount", "COGS",
         "Platform_Fee_Cost", "Fulfillment_Cost", "Affiliate_Cost", "Sample_Cost", "Claim_Cost"]


def build(rows):
    db = duckdb.connect()
    db.execute("CREATE TABLE Dim_Date(Date_Key INT, Year_Month VARCHAR)")
    db.execute("INSERT INTO Dim_Date VALUES (20260601,'2026-06'),(20260602,'2026-06'),(20260701,'2026-07')")
    cols = ", ".join(c + " DOUBLE" for c in COSTS)
    db.execute(f"CREATE TABLE Mart_Product_Group_Daily_Performance(Date_Key INT, Product_Group_ID VARCHAR, Product_Group_Name VARCHAR, {cols}, "
               "Contribution_Profit DOUBLE, Data_Cost_Basis VARCHAR)")
    for i, (date, group, basis) in enumerate(rows):
        vals = [100.0 + i * 7 + j for j in range(len(COSTS))]
        profit = None if basis == "INCOMPLETE" else vals[0] - sum(vals[3:])
        db.execute("INSERT INTO Mart_Product_Group_Daily_Performance VALUES (?,?,?,"+",".join("?" * len(COSTS))+",?,?)",
                   [date, group, "name-" + group, *vals, profit, basis])
    return db


def test_group_costs_sum_to_the_month_total_for_every_cost_column():
    db = build([(20260601, "PG01", "MOCK_ACTUAL_WITH_POLICY_FEE"), (20260602, "PG01", "MOCK_ACTUAL_WITH_POLICY_FEE"),
                (20260601, "PG02", "MOCK_ACTUAL_WITH_POLICY_FEE"), (20260701, "PG02", "MOCK_ACTUAL_WITH_POLICY_FEE")])
    groups = db.execute(GROUPS_SQL).df().to_dict("records")
    keys = {"Net_Revenue": "net", "Gross_Reference_Sales": "gross", "Ads_Cost": "ads_cost", "Campaign_Price_Reduction": "campaign_reduction",
            "Voucher_Discount": "voucher_discount", "COGS": "cogs", "Platform_Fee_Cost": "platform_fee", "Fulfillment_Cost": "fulfillment",
            "Affiliate_Cost": "affiliate", "Sample_Cost": "sample", "Claim_Cost": "claim"}
    for month in ("2026-06", "2026-07"):
        for column, key in keys.items():
            expected = db.execute(f"SELECT SUM(m.{column}) FROM Mart_Product_Group_Daily_Performance m JOIN Dim_Date d ON d.Date_Key=m.Date_Key "
                                  "WHERE d.Year_Month=?", [month]).fetchone()[0]
            assert abs(sum(g[key] for g in groups if g["month"] == month) - expected) < 1e-6, (month, column)


def test_incomplete_group_reports_null_profit_and_incomplete_rows_instead_of_zero():
    db = build([(20260601, "PG01", "MOCK_ACTUAL_WITH_POLICY_FEE"), (20260601, "PG02", "INCOMPLETE"), (20260602, "PG02", "MOCK_ACTUAL_WITH_POLICY_FEE")])
    by = {g["group_id"]: g for g in db.execute(GROUPS_SQL).df().to_dict("records")}
    assert by["PG01"]["incomplete_rows"] == 0 and by["PG01"]["profit"] == by["PG01"]["profit"]
    assert by["PG02"]["incomplete_rows"] == 1 and by["PG02"]["profit"] != by["PG02"]["profit"]      # NaN == NULL, never 0
