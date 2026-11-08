-- Neon PostgreSQL 17 classroom ER1 schema; generated from schemas/ER1_V3.dbml.

-- 25 business tables, 26 FKs, six separate operational control tables.

-- Safe to rerun for initial bootstrap; does NOT delete data, clear results, or reset counters.

CREATE SCHEMA IF NOT EXISTS demo_er1;

CREATE SCHEMA IF NOT EXISTS demo_control;

CREATE TABLE IF NOT EXISTS demo_er1."Dim_Product_Group" (
  "Product_Group_ID" TEXT,
  "Product_Group_Name" TEXT,
  "Base_Selling_Price" NUMERIC(20,4),
  "Cost_Standard_Product" NUMERIC(20,4),
  "Status" TEXT,
  PRIMARY KEY ("Product_Group_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Dim_SKU" (
  "SKU_ID" TEXT,
  "Product_Group_ID" TEXT NOT NULL,
  "SKU_Name" TEXT,
  "Color" TEXT,
  "Size" TEXT,
  "Status" TEXT,
  PRIMARY KEY ("SKU_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Dim_Creator" (
  "Creator_ID" TEXT,
  "Creator_Name" TEXT,
  "Creator_Type" TEXT,
  "Status" TEXT,
  PRIMARY KEY ("Creator_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Dim_Campaign" (
  "Campaign_ID" TEXT,
  "Campaign_Name" TEXT,
  "Campaign_Type" TEXT,
  "Start_Date" DATE,
  "End_Date" DATE,
  PRIMARY KEY ("Campaign_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Dim_Ad_Campaign" (
  "Ad_Campaign_ID" TEXT,
  "Ad_Campaign_Name" TEXT,
  "Ad_Type" TEXT,
  "Start_Date" DATE,
  "End_Date" DATE,
  PRIMARY KEY ("Ad_Campaign_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Dim_Voucher" (
  "Voucher_ID" TEXT,
  "Voucher_Name" TEXT,
  "Discount_Rate" NUMERIC(20,4) NOT NULL,
  "Minimum_Spend_Amount" NUMERIC(20,4) NOT NULL,
  "Maximum_Discount_Amount" NUMERIC(20,4),
  "Is_Active" BOOLEAN NOT NULL,
  "Effective_From" DATE,
  "Effective_To" DATE,
  PRIMARY KEY ("Voucher_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Bridge_Campaign_Product_Group" (
  "Enrollment_ID" TEXT,
  "Campaign_ID" TEXT NOT NULL,
  "Product_Group_ID" TEXT NOT NULL,
  "Campaign_Selling_Price" NUMERIC(20,4),
  "Effective_From" DATE,
  "Effective_To" DATE,
  "Status" TEXT,
  PRIMARY KEY ("Enrollment_ID"),
  UNIQUE ("Campaign_ID", "Product_Group_ID", "Effective_From")
);

CREATE TABLE IF NOT EXISTS demo_er1."Bridge_Voucher_Product_Group" (
  "Voucher_ID" TEXT NOT NULL,
  "Product_Group_ID" TEXT NOT NULL,
  PRIMARY KEY ("Voucher_ID", "Product_Group_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Ref_Affiliate_Commission_Rule" (
  "Affiliate_Rule_ID" TEXT,
  "Product_Group_ID" TEXT NOT NULL,
  "Affiliate_Commission_Rate" NUMERIC(20,4),
  "Effective_From" DATE,
  "Effective_To" DATE,
  "Is_Active" BOOLEAN,
  PRIMARY KEY ("Affiliate_Rule_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Ref_Platform_Fee_Estimate_Rule" (
  "Platform_Fee_Rule_ID" TEXT,
  "Product_Group_ID" TEXT NOT NULL,
  "Total_Platform_Fee_Rate" NUMERIC(20,4),
  "Fee_Calculation_Mode" TEXT,
  "Platform_Commission_Rate" NUMERIC(20,4),
  "Transaction_Fee_Rate" NUMERIC(20,4),
  "Commerce_Growth_Fee_Rate" NUMERIC(20,4),
  "Infrastructure_Fee_Per_Order" NUMERIC(20,4),
  "Effective_From" DATE,
  "Effective_To" DATE,
  "Is_Mock_Assumption" BOOLEAN,
  PRIMARY KEY ("Platform_Fee_Rule_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Ref_Business_Target" (
  "Target_Year_Month" TEXT,
  "Revenue_Target" NUMERIC(20,4) NOT NULL,
  "Minimum_Profit_Protection_Rate" NUMERIC(20,4) NOT NULL,
  PRIMARY KEY ("Target_Year_Month")
);

CREATE TABLE IF NOT EXISTS demo_er1."Ref_Cost_Policy" (
  "Cost_Policy_ID" TEXT,
  "Fixed_Fulfillment_Cost_Per_Order" NUMERIC(20,4),
  "Claim_Risk_Allowance_Rate" NUMERIC(20,4),
  "Planning_Base_Cost_Rate" NUMERIC(20,4),
  "Planning_Adjustable_Gap_Rate" NUMERIC(20,4),
  "Effective_From" DATE NOT NULL,
  "Effective_To" DATE,
  "Is_Active" BOOLEAN NOT NULL,
  PRIMARY KEY ("Cost_Policy_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Fact_Goods_Receipt" (
  "Goods_Receipt_ID" TEXT,
  "Receipt_Date" TIMESTAMP,
  "Supplier_ID" TEXT,
  "Reference_PO_ID" TEXT,
  "Source_System" TEXT,
  PRIMARY KEY ("Goods_Receipt_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Fact_Goods_Receipt_Items" (
  "Goods_Receipt_Item_ID" TEXT,
  "Goods_Receipt_ID" TEXT NOT NULL,
  "SKU_ID" TEXT NOT NULL,
  "Received_Qty" INTEGER NOT NULL,
  "Unit_Cost" NUMERIC(20,4) NOT NULL,
  "Total_Cost" NUMERIC(20,4),
  "Remaining_Qty" INTEGER,
  "Lot_No" TEXT,
  PRIMARY KEY ("Goods_Receipt_Item_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Fact_Orders" (
  "Order_ID" TEXT,
  "Order_Created_At" TIMESTAMP,
  "Current_Status" TEXT,
  "Voucher_ID" TEXT,
  "GMV_Total" NUMERIC(20,4),
  "Voucher_Seller_Cost" NUMERIC(20,4),
  "Shipping_Fee_Collected" NUMERIC(20,4),
  "Shipping_Mode" TEXT,
  "Paid_At" TIMESTAMP,
  "Shipped_At" TIMESTAMP,
  "Delivered_At" TIMESTAMP,
  "Cancelled_At" TIMESTAMP,
  PRIMARY KEY ("Order_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Fact_Order_Items" (
  "Order_Item_ID" TEXT,
  "Source_Order_Item_ID" TEXT,
  "Order_ID" TEXT NOT NULL,
  "SKU_ID" TEXT NOT NULL,
  "Quantity" INTEGER NOT NULL,
  "Creator_ID" TEXT,
  "Campaign_ID" TEXT,
  "Base_Unit_Price_At_Sale" NUMERIC(20,4),
  "Unit_Selling_Price" NUMERIC(20,4),
  "Campaign_Discount_Amount" NUMERIC(20,4),
  "Voucher_Allocated_Amount" NUMERIC(20,4) NOT NULL,
  "Total_Selling_Amount" NUMERIC(20,4),
  "Total_COGS" NUMERIC(20,4),
  "Fee_Affiliate_Payout" NUMERIC(20,4),
  "Created_At" TIMESTAMP,
  PRIMARY KEY ("Order_Item_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Fact_FIFO_Allocation" (
  "FIFO_Allocation_ID" TEXT,
  "Order_Item_ID" TEXT NOT NULL,
  "Goods_Receipt_Item_ID" TEXT NOT NULL,
  "Allocated_Qty" INTEGER NOT NULL,
  "Unit_Cost" NUMERIC(20,4) NOT NULL,
  "Allocated_Cost" NUMERIC(20,4) NOT NULL,
  "Allocated_At" TIMESTAMP,
  PRIMARY KEY ("FIFO_Allocation_ID"),
  UNIQUE ("Order_Item_ID", "Goods_Receipt_Item_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Fact_Order_Platform_Fees" (
  "Platform_Fee_ID" TEXT,
  "Order_ID" TEXT NOT NULL,
  "Fee_Platform_Commission" NUMERIC(20,4),
  "Fee_Transaction" NUMERIC(20,4),
  "Fee_Commerce_Growth" NUMERIC(20,4),
  "Fee_Platform_Infrastructure" NUMERIC(20,4),
  PRIMARY KEY ("Platform_Fee_ID"),
  UNIQUE ("Order_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Fact_Internal_Fulfillment" (
  "Fulfillment_ID" TEXT,
  "Order_ID" TEXT NOT NULL,
  "Secondary_Packaging_Cost" NUMERIC(20,4),
  "Packing_Labor_Cost" NUMERIC(20,4),
  "Actual_Shipping_Cost" NUMERIC(20,4),
  "Fulfillment_Timestamp" TIMESTAMP,
  PRIMARY KEY ("Fulfillment_ID"),
  UNIQUE ("Order_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Fact_Marketing_Costs" (
  "Ad_Record_ID" TEXT,
  "Record_Date" DATE,
  "Ad_Campaign_ID" TEXT NOT NULL,
  "Product_Group_ID" TEXT NOT NULL,
  "Ad_Spend_Amount" NUMERIC(20,4),
  "Impressions" INTEGER,
  "Clicks" INTEGER,
  "Conversions" INTEGER,
  "Reported_Ads_GMV" NUMERIC(20,4),
  "Reported_Ads_Orders" INTEGER,
  "Reported_Revenue_Basis" TEXT,
  PRIMARY KEY ("Ad_Record_ID"),
  UNIQUE ("Record_Date", "Ad_Campaign_ID", "Product_Group_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Fact_Claim_Header" (
  "Claim_ID" TEXT,
  "Claim_Date" TIMESTAMP,
  "Claim_Reason" TEXT,
  "Claim_Status" TEXT,
  PRIMARY KEY ("Claim_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Fact_Claim_Details" (
  "Claim_Detail_ID" TEXT,
  "Claim_ID" TEXT NOT NULL,
  "Order_Item_ID" TEXT NOT NULL,
  "Claim_Qty" INTEGER NOT NULL,
  "Replacement_Qty" INTEGER,
  "Return_Qty" INTEGER,
  "Disposal_Qty" INTEGER,
  "Backend_Packing_Cost" NUMERIC(20,4),
  "Backend_Shipping_Cost" NUMERIC(20,4),
  "Replacement_Product_Cost" NUMERIC(20,4),
  "Disposal_Loss_Cost" NUMERIC(20,4),
  "Backend_Action_Date" TIMESTAMP,
  PRIMARY KEY ("Claim_Detail_ID"),
  UNIQUE ("Claim_ID", "Order_Item_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Fact_Free_Samples" (
  "Sample_ID" TEXT,
  "SKU_ID" TEXT NOT NULL,
  "Creator_ID" TEXT NOT NULL,
  "Sample_Quantity" INTEGER,
  "Request_Date" TIMESTAMP,
  "Dispatched_Date" TIMESTAMP,
  "Sample_Shipping_Cost" NUMERIC(20,4),
  "Sample_COGS" NUMERIC(20,4),
  PRIMARY KEY ("Sample_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Fact_Stock_Movement" (
  "Stock_Movement_ID" TEXT,
  "Event_Timestamp" TIMESTAMP,
  "SKU_ID" TEXT NOT NULL,
  "Movement_Type" TEXT,
  "Quantity" INTEGER,
  "Unit_Cost" NUMERIC(20,4),
  "Total_Cost" NUMERIC(20,4),
  "Reference_ID" TEXT,
  "Source_System" TEXT,
  PRIMARY KEY ("Stock_Movement_ID")
);

CREATE TABLE IF NOT EXISTS demo_er1."Fact_Inventory_Snapshot" (
  "Snapshot_ID" TEXT,
  "Snapshot_Timestamp" TIMESTAMP,
  "SKU_ID" TEXT NOT NULL,
  "Ending_Physical_Qty" INTEGER,
  "TikTok_Listed_Available_Qty" INTEGER,
  "TikTok_Order_Reserved_Qty" INTEGER,
  "TikTok_Unavailable_Qty" INTEGER,
  "Internal_Available_Qty" INTEGER,
  "Claim_Buffer_Qty" INTEGER,
  "Creator_Buffer_Qty" INTEGER,
  "Free_Stock_Qty" INTEGER,
  "Inventory_Value" NUMERIC(20,4),
  PRIMARY KEY ("Snapshot_ID"),
  UNIQUE ("Snapshot_Timestamp", "SKU_ID")
);

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Dim_SKU_Product_Group_ID') THEN
  ALTER TABLE demo_er1."Dim_SKU" ADD CONSTRAINT "fk_Dim_SKU_Product_Group_ID" FOREIGN KEY ("Product_Group_ID") REFERENCES demo_er1."Dim_Product_Group" ("Product_Group_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Bridge_Campaign_Product_Group_Campaign_ID') THEN
  ALTER TABLE demo_er1."Bridge_Campaign_Product_Group" ADD CONSTRAINT "fk_Bridge_Campaign_Product_Group_Campaign_ID" FOREIGN KEY ("Campaign_ID") REFERENCES demo_er1."Dim_Campaign" ("Campaign_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Bridge_Campaign_Product_Group_Product_Group_ID') THEN
  ALTER TABLE demo_er1."Bridge_Campaign_Product_Group" ADD CONSTRAINT "fk_Bridge_Campaign_Product_Group_Product_Group_ID" FOREIGN KEY ("Product_Group_ID") REFERENCES demo_er1."Dim_Product_Group" ("Product_Group_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Ref_Affiliate_Commission_Rule_Product_Group_ID') THEN
  ALTER TABLE demo_er1."Ref_Affiliate_Commission_Rule" ADD CONSTRAINT "fk_Ref_Affiliate_Commission_Rule_Product_Group_ID" FOREIGN KEY ("Product_Group_ID") REFERENCES demo_er1."Dim_Product_Group" ("Product_Group_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Ref_Platform_Fee_Estimate_Rule_Product_Group_ID') THEN
  ALTER TABLE demo_er1."Ref_Platform_Fee_Estimate_Rule" ADD CONSTRAINT "fk_Ref_Platform_Fee_Estimate_Rule_Product_Group_ID" FOREIGN KEY ("Product_Group_ID") REFERENCES demo_er1."Dim_Product_Group" ("Product_Group_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Goods_Receipt_Items_Goods_Receipt_ID') THEN
  ALTER TABLE demo_er1."Fact_Goods_Receipt_Items" ADD CONSTRAINT "fk_Fact_Goods_Receipt_Items_Goods_Receipt_ID" FOREIGN KEY ("Goods_Receipt_ID") REFERENCES demo_er1."Fact_Goods_Receipt" ("Goods_Receipt_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Goods_Receipt_Items_SKU_ID') THEN
  ALTER TABLE demo_er1."Fact_Goods_Receipt_Items" ADD CONSTRAINT "fk_Fact_Goods_Receipt_Items_SKU_ID" FOREIGN KEY ("SKU_ID") REFERENCES demo_er1."Dim_SKU" ("SKU_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Bridge_Voucher_Product_Group_Voucher_ID') THEN
  ALTER TABLE demo_er1."Bridge_Voucher_Product_Group" ADD CONSTRAINT "fk_Bridge_Voucher_Product_Group_Voucher_ID" FOREIGN KEY ("Voucher_ID") REFERENCES demo_er1."Dim_Voucher" ("Voucher_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Bridge_Voucher_Product_Group_Product_Group_ID') THEN
  ALTER TABLE demo_er1."Bridge_Voucher_Product_Group" ADD CONSTRAINT "fk_Bridge_Voucher_Product_Group_Product_Group_ID" FOREIGN KEY ("Product_Group_ID") REFERENCES demo_er1."Dim_Product_Group" ("Product_Group_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Orders_Voucher_ID') THEN
  ALTER TABLE demo_er1."Fact_Orders" ADD CONSTRAINT "fk_Fact_Orders_Voucher_ID" FOREIGN KEY ("Voucher_ID") REFERENCES demo_er1."Dim_Voucher" ("Voucher_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Order_Items_Order_ID') THEN
  ALTER TABLE demo_er1."Fact_Order_Items" ADD CONSTRAINT "fk_Fact_Order_Items_Order_ID" FOREIGN KEY ("Order_ID") REFERENCES demo_er1."Fact_Orders" ("Order_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Order_Items_SKU_ID') THEN
  ALTER TABLE demo_er1."Fact_Order_Items" ADD CONSTRAINT "fk_Fact_Order_Items_SKU_ID" FOREIGN KEY ("SKU_ID") REFERENCES demo_er1."Dim_SKU" ("SKU_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Order_Items_Creator_ID') THEN
  ALTER TABLE demo_er1."Fact_Order_Items" ADD CONSTRAINT "fk_Fact_Order_Items_Creator_ID" FOREIGN KEY ("Creator_ID") REFERENCES demo_er1."Dim_Creator" ("Creator_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Order_Items_Campaign_ID') THEN
  ALTER TABLE demo_er1."Fact_Order_Items" ADD CONSTRAINT "fk_Fact_Order_Items_Campaign_ID" FOREIGN KEY ("Campaign_ID") REFERENCES demo_er1."Dim_Campaign" ("Campaign_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_FIFO_Allocation_Order_Item_ID') THEN
  ALTER TABLE demo_er1."Fact_FIFO_Allocation" ADD CONSTRAINT "fk_Fact_FIFO_Allocation_Order_Item_ID" FOREIGN KEY ("Order_Item_ID") REFERENCES demo_er1."Fact_Order_Items" ("Order_Item_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_FIFO_Allocation_Goods_Receipt_Item_ID') THEN
  ALTER TABLE demo_er1."Fact_FIFO_Allocation" ADD CONSTRAINT "fk_Fact_FIFO_Allocation_Goods_Receipt_Item_ID" FOREIGN KEY ("Goods_Receipt_Item_ID") REFERENCES demo_er1."Fact_Goods_Receipt_Items" ("Goods_Receipt_Item_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Order_Platform_Fees_Order_ID') THEN
  ALTER TABLE demo_er1."Fact_Order_Platform_Fees" ADD CONSTRAINT "fk_Fact_Order_Platform_Fees_Order_ID" FOREIGN KEY ("Order_ID") REFERENCES demo_er1."Fact_Orders" ("Order_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Internal_Fulfillment_Order_ID') THEN
  ALTER TABLE demo_er1."Fact_Internal_Fulfillment" ADD CONSTRAINT "fk_Fact_Internal_Fulfillment_Order_ID" FOREIGN KEY ("Order_ID") REFERENCES demo_er1."Fact_Orders" ("Order_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Marketing_Costs_Ad_Campaign_ID') THEN
  ALTER TABLE demo_er1."Fact_Marketing_Costs" ADD CONSTRAINT "fk_Fact_Marketing_Costs_Ad_Campaign_ID" FOREIGN KEY ("Ad_Campaign_ID") REFERENCES demo_er1."Dim_Ad_Campaign" ("Ad_Campaign_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Marketing_Costs_Product_Group_ID') THEN
  ALTER TABLE demo_er1."Fact_Marketing_Costs" ADD CONSTRAINT "fk_Fact_Marketing_Costs_Product_Group_ID" FOREIGN KEY ("Product_Group_ID") REFERENCES demo_er1."Dim_Product_Group" ("Product_Group_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Claim_Details_Claim_ID') THEN
  ALTER TABLE demo_er1."Fact_Claim_Details" ADD CONSTRAINT "fk_Fact_Claim_Details_Claim_ID" FOREIGN KEY ("Claim_ID") REFERENCES demo_er1."Fact_Claim_Header" ("Claim_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Claim_Details_Order_Item_ID') THEN
  ALTER TABLE demo_er1."Fact_Claim_Details" ADD CONSTRAINT "fk_Fact_Claim_Details_Order_Item_ID" FOREIGN KEY ("Order_Item_ID") REFERENCES demo_er1."Fact_Order_Items" ("Order_Item_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Free_Samples_SKU_ID') THEN
  ALTER TABLE demo_er1."Fact_Free_Samples" ADD CONSTRAINT "fk_Fact_Free_Samples_SKU_ID" FOREIGN KEY ("SKU_ID") REFERENCES demo_er1."Dim_SKU" ("SKU_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Free_Samples_Creator_ID') THEN
  ALTER TABLE demo_er1."Fact_Free_Samples" ADD CONSTRAINT "fk_Fact_Free_Samples_Creator_ID" FOREIGN KEY ("Creator_ID") REFERENCES demo_er1."Dim_Creator" ("Creator_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Stock_Movement_SKU_ID') THEN
  ALTER TABLE demo_er1."Fact_Stock_Movement" ADD CONSTRAINT "fk_Fact_Stock_Movement_SKU_ID" FOREIGN KEY ("SKU_ID") REFERENCES demo_er1."Dim_SKU" ("SKU_ID");
 END IF;
END $constraint$;

DO $constraint$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint x JOIN pg_namespace n ON n.oid=x.connamespace WHERE n.nspname='demo_er1' AND x.conname='fk_Fact_Inventory_Snapshot_SKU_ID') THEN
  ALTER TABLE demo_er1."Fact_Inventory_Snapshot" ADD CONSTRAINT "fk_Fact_Inventory_Snapshot_SKU_ID" FOREIGN KEY ("SKU_ID") REFERENCES demo_er1."Dim_SKU" ("SKU_ID");
 END IF;
END $constraint$;

CREATE TABLE IF NOT EXISTS demo_control.dataset_state (
 dataset_key TEXT PRIMARY KEY CHECK(dataset_key='classroom'),
 cycle_number INTEGER NOT NULL DEFAULT 1 CHECK(cycle_number>=1),
 phase TEXT NOT NULL DEFAULT 'EMPTY' CHECK(phase IN ('EMPTY','RUN1_READY','RUN2_READY')),
 lock_version BIGINT NOT NULL DEFAULT 0,
 last_run_id UUID,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO demo_control.dataset_state(dataset_key) VALUES ('classroom') ON CONFLICT (dataset_key) DO NOTHING;

CREATE TABLE IF NOT EXISTS demo_control.pipeline_runs (
 run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 dataset_key TEXT NOT NULL DEFAULT 'classroom' REFERENCES demo_control.dataset_state(dataset_key),
 cycle_number INTEGER NOT NULL CHECK(cycle_number>=1),
 run_type TEXT NOT NULL CHECK(run_type IN ('RUN1','RUN2','REPLAY','ERROR_TEST')),
 request_key TEXT NOT NULL CHECK(length(request_key)>0),
 status TEXT NOT NULL DEFAULT 'QUEUED' CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
 source_digest TEXT,
 runner_ref TEXT,
 triggered_by TEXT,
 started_at TIMESTAMPTZ,
 finished_at TIMESTAMPTZ,
 result_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
 error_message TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(dataset_key,cycle_number,run_type,request_key)
);

CREATE TABLE IF NOT EXISTS demo_control.stage_runs (
 run_id UUID NOT NULL REFERENCES demo_control.pipeline_runs(run_id),
 stage_name TEXT NOT NULL CHECK(stage_name IN ('ingest','extract','transform','load','validate')),
 status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','SUCCESS','FAILED','SKIPPED')),
 started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
 metrics JSONB NOT NULL DEFAULT '{}'::jsonb, error_message TEXT,
 PRIMARY KEY(run_id,stage_name)
);

CREATE TABLE IF NOT EXISTS demo_control.reset_audit (
 reset_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 dataset_key TEXT NOT NULL DEFAULT 'classroom',
 previous_cycle INTEGER NOT NULL CHECK(previous_cycle>=1),
 next_cycle INTEGER NOT NULL CHECK(next_cycle=previous_cycle+1),
 actor TEXT NOT NULL,
 reason TEXT,
 data_tables_cleared INTEGER NOT NULL DEFAULT 0,
 completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 status TEXT NOT NULL CHECK(status IN ('SUCCEEDED','FAILED'))
);

CREATE TABLE IF NOT EXISTS demo_control.pipeline_artifacts (
 artifact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 run_id UUID NOT NULL REFERENCES demo_control.pipeline_runs(run_id),
 stage_name TEXT NOT NULL CHECK(stage_name IN ('ingest','extract','transform','load','validate')),
 artifact_type TEXT NOT NULL CHECK(artifact_type IN ('SOURCE','DATABASE','LAKE_LANDING','LAKE_RAW','LAKE_STANDARDIZED','WAREHOUSE','REPORT','MODEL')),
 artifact_uri TEXT NOT NULL,
 content_sha256 TEXT CHECK(content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'),
 records_count BIGINT CHECK(records_count IS NULL OR records_count>=0),
 size_bytes BIGINT CHECK(size_bytes IS NULL OR size_bytes>=0),
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(run_id,artifact_type,artifact_uri)
);

CREATE TABLE IF NOT EXISTS demo_control.stage_events (
 event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 run_id UUID NOT NULL REFERENCES demo_control.pipeline_runs(run_id),
 stage_name TEXT NOT NULL CHECK(stage_name IN ('ingest','extract','transform','load','validate')),
 event_type TEXT NOT NULL CHECK(event_type IN ('STARTED','SUCCEEDED','FAILED','RETRIED','SKIPPED')),
 occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(), message TEXT,
 details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_stage_events_run_time ON demo_control.stage_events(run_id,occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_artifacts_run ON demo_control.pipeline_artifacts(run_id,stage_name);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_recent ON demo_control.pipeline_runs(dataset_key,cycle_number,created_at DESC);
