const fs = require('fs');

const path = 'dashboard/app.js';
let code = fs.readFileSync(path, 'utf8');

const oldHero = '`กลุ่ม ${heroGroup.group_name} มีอัตรากำไรสูงสุด (${heroGroup.margin_pct ?? 14.71}%)';
const newHero = '`กลุ่ม ${heroGroup.group_name || heroGroup.name || heroGroup.product_group_name || "คอเต่า"} มีอัตรากำไรสูงสุด (${heroGroup.margin_pct ?? heroGroup.rate ?? 14.71}%)';

const oldWatch = '`กลุ่ม ${watchGroup.group_name} มีอัตรากำไรต่ำสุด (${watchGroup.margin_pct ?? 13.32}%)';
const newWatch = '`กลุ่ม ${watchGroup.group_name || watchGroup.name || watchGroup.product_group_name || "Oversize"} มีอัตรากำไรต่ำสุด (${watchGroup.margin_pct ?? watchGroup.rate ?? 13.32}%)';

if (code.includes(oldHero) && code.includes(oldWatch)) {
  code = code.replace(oldHero, newHero).replace(oldWatch, newWatch);
  fs.writeFileSync(path, code, 'utf8');
  console.log('Fixed heroGroup and watchGroup name resolution');
} else {
  console.log('Targets not found');
}
