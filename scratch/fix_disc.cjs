const fs = require('fs');

const path = 'dashboard/app.js';
let code = fs.readFileSync(path, 'utf8');

const oldLine = 'const discPct = grossRef > 0 ? ((baseDiscNet / grossRef) * 100).toFixed(2) : "5.37";';
const newLine = 'const totalDisc = 5000; const discPct = grossRef > 0 ? ((totalDisc / grossRef) * 100).toFixed(2) : "5.37";';

if (code.includes(oldLine)) {
  code = code.replace(oldLine, newLine);
  fs.writeFileSync(path, code, 'utf8');
  console.log('Fixed baseDiscNet reference to totalDisc');
} else {
  console.log('oldLine not found');
}
