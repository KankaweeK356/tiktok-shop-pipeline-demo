import fs from "fs";
import path from "path";

const dir = "source/initial";
const files = fs.readdirSync(dir).filter(f => f.endsWith(".csv")).sort();
const result = {};

for (const f of files) {
  const content = fs.readFileSync(path.join(dir, f), "utf8").trim();
  const lines = content.split("\n");
  const headers = lines[0].split(",").map(s => s.trim().replace(/^"|"$/g, ""));
  const rows = lines.slice(1).map(line => {
    const parts = line.split(",").map(s => s.trim().replace(/^"|"$/g, ""));
    const obj = {};
    headers.forEach((h, i) => { obj[h] = parts[i] || ""; });
    return obj;
  });
  result[f] = {
    file_name: f,
    table_name: f.replace(".csv", ""),
    row_count: rows.length,
    column_count: headers.length,
    headers: headers,
    sample_rows: rows.slice(0, 5)
  };
}

fs.writeFileSync("dashboard/data/source_initial_samples.json", JSON.stringify(result, null, 2));
console.log("Saved", Object.keys(result).length, "CSV samples to dashboard/data/source_initial_samples.json");
