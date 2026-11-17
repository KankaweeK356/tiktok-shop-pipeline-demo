const fs = require('fs');

const path = 'dashboard/app.js';
let code = fs.readFileSync(path, 'utf8');

const oldBlock = `    // [R03-HERO-PORTFOLIO] & [R04-MARGIN-WATCH]
    if (groups.length > 0) {
      const sortedGroups = groups.slice().sort((a, b) => (b.margin_pct ?? 0) - (a.margin_pct ?? 0));
      const heroGroup = sortedGroups[0];
      const watchGroup = sortedGroups[sortedGroups.length - 1];
      recs.push({
        id: "R03-HERO-PORTFOLIO",
        icon: "⭐",
        tag: "[R03-HERO-PORTFOLIO]",
        text: \`กลุ่ม \${heroGroup.group_name || heroGroup.name || heroGroup.product_group_name || "คอเต่า"} มีอัตรากำไรสูงสุด (\${heroGroup.margin_pct ?? heroGroup.rate ?? 14.71}%) ควรคงสัดส่วนเป็น Hero Products และจัดสรรงบ Ads หลัก\`
      });
      recs.push({
        id: "R04-MARGIN-WATCH",
        icon: "🔍",
        tag: "[R04-MARGIN-WATCH]",
        text: \`กลุ่ม \${watchGroup.group_name || watchGroup.name || watchGroup.product_group_name || "Oversize"} มีอัตรากำไรต่ำสุด (\${watchGroup.margin_pct ?? watchGroup.rate ?? 13.32}%) ควรควบคุมค่า Ads และส่วนลดไม่ให้กระทบ Margin รวม\`
      });
    }`;

const newBlock = `    // [R03-HERO-PORTFOLIO] & [R04-MARGIN-WATCH]
    if (groupRows.length > 0) {
      const sortedGroups = groupRows.slice().sort((a, b) => (b.rate ?? 0) - (a.rate ?? 0));
      const heroGroup = sortedGroups[0];
      const watchGroup = sortedGroups[sortedGroups.length - 1];
      recs.push({
        id: "R03-HERO-PORTFOLIO",
        icon: "⭐",
        tag: "[R03-HERO-PORTFOLIO]",
        text: \`กลุ่ม \${heroGroup.group_name} มีอัตรากำไรสูงสุด (\${heroGroup.rate}%) ควรคงสัดส่วนเป็น Hero Products และจัดสรรงบ Ads หลัก\`
      });
      recs.push({
        id: "R04-MARGIN-WATCH",
        icon: "🔍",
        tag: "[R04-MARGIN-WATCH]",
        text: \`กลุ่ม \${watchGroup.group_name} มีอัตรากำไรต่ำสุด (\${watchGroup.rate}%) ควรควบคุมค่า Ads และส่วนลดไม่ให้กระทบ Margin รวม\`
      });
    }`;

const normCode = code.replace(/\r\n/g, '\n');
const normOld = oldBlock.replace(/\r\n/g, '\n');
const normNew = newBlock.replace(/\r\n/g, '\n');

if (normCode.includes(normOld)) {
  code = normCode.replace(normOld, normNew);
  fs.writeFileSync(path, code, 'utf8');
  console.log('Fixed groupRows in Decision Recommendations');
} else {
  console.log('Targets not found');
}
