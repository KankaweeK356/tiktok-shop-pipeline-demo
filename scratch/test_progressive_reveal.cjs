const fs = require('fs');
const path = require('path');

const appJs = fs.readFileSync(path.resolve(__dirname, '../dashboard/app.js'), 'utf8');

// Test that FALLBACK_BUSINESS_DATA is completely gone
if (appJs.includes('FALLBACK_BUSINESS_DATA')) {
  console.error('FAIL: FALLBACK_BUSINESS_DATA is still in app.js!');
  process.exit(1);
} else {
  console.log('PASS: FALLBACK_BUSINESS_DATA removed completely from runtime.');
}

// Test that hardcoded sampleMonths and protMonths are gone
if (appJs.includes('const sampleMonths = [') || appJs.includes('const protMonths = [')) {
  console.error('FAIL: sampleMonths or protMonths still present!');
  process.exit(1);
} else {
  console.log('PASS: sampleMonths and protMonths removed.');
}

// Check presence of key Progressive Reveal components
const requiredStrings = [
  'getPublishedMonths',
  'getPublishedMonthData',
  'single-month-card',
  'bullet-track',
  'bullet-target-marker',
  'single-month-gauge-box',
  'gauge-rate-large',
  'ml-readiness-box',
  'ml-progress-track',
  'ml-progress-fill',
  '[⏳ INSUFFICIENT_HISTORY]',
  'ยังไม่มีข้อมูลที่ผ่านการประมวลผลและ Publish จาก Data Warehouse'
];

let allPassed = true;
requiredStrings.forEach(str => {
  if (!appJs.includes(str)) {
    console.error(`FAIL: Missing required progressive reveal string: "${str}"`);
    allPassed = false;
  } else {
    console.log(`PASS: Found "${str}"`);
  }
});

if (!allPassed) {
  process.exit(1);
}

console.log('\nALL PROGRESSIVE REVEAL COMPONENT CHECKS PASSED!');
