/** Download Warehouse CSV archive generated directly on Vercel.
 * Zero reliance on GitHub Actions artifacts.
 */
import { zipSync, strToU8 } from "fflate";
import reportData from "../dashboard/data/report.json" with { type: "json" };

function toCsv(rows) {
  if (!rows || !rows.length) return "";
  const headers = Object.keys(rows[0]);
  const lines = [headers.join(",")];
  for (const row of rows) {
    lines.push(headers.map(h => {
      const val = row[h];
      if (val === null || val === undefined) return "";
      const str = String(val);
      return str.includes(",") || str.includes('"') || str.includes("\n") ?
        `"${str.replace(/"/g, '""')}"` : str;
    }).join(","));
  }
  return lines.join("\n");
}

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "GET") return res.status(405).json({ error: "GET only" });

  const id = String(req.query?.run_id || "latest");

  try {
    const months = reportData.business?.months || [];
    const groups = reportData.business?.groups || [];
    const sku = reportData.business?.sku || [];

    const zipFiles = {
      "View_Shop_Monthly_KPI.csv": strToU8(toCsv(months)),
      "Mart_Product_Group_Daily_Performance.csv": strToU8(toCsv(groups)),
      "Fact_Sales_Order_Item.csv": strToU8(toCsv(sku.map(s => ({
        Order_Item_ID: `ITM_${s.sku_id}_01`,
        SKU_ID: s.sku_id,
        SKU_Name: s.sku_name,
        Product_Group_ID: s.group_id,
        Net_Revenue: s.net,
        Cost_Basis: s.cost_basis
      }))))
    };

    const zipped = zipSync(zipFiles);

    res.setHeader("Content-Type", "application/zip");
    res.setHeader("Content-Disposition", `attachment; filename="classroom-warehouse-run-${id}.zip"`);
    return res.status(200).send(Buffer.from(zipped));
  } catch (error) {
    console.error("Warehouse download failed", error?.message);
    return res.status(500).json({ error: "ดาวน์โหลด Warehouse ไม่สำเร็จ: " + error?.message });
  }
}
