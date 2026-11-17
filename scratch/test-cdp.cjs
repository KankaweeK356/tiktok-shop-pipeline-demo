const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');

const ARTIFACT_DIR = 'C:\\Users\\kankawee.k\\.gemini\\antigravity\\brain\\247e4374-55e6-40c9-9b7d-8a1a8705b6c5';
const PROFILE_DIR = path.join(ARTIFACT_DIR, 'scratch', 'chrome-profile');
const TARGET_URL = 'https://tiktok-shop-mlops-dashboard-git-feature-classroom-dea39b-newja.vercel.app';
const PORT = 9222;

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function fetchJson(url) {
  return new Promise((resolve, reject) => {
    http.get(url, res => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch (e) {
          reject(e);
        }
      });
    }).on('error', reject);
  });
}

class CDPClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = null;
    this.id = 1;
    this.callbacks = new Map();
  }

  connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.wsUrl);
      this.ws.onopen = () => resolve();
      this.ws.onerror = err => reject(err);
      this.ws.onmessage = evt => {
        const msg = JSON.parse(evt.data);
        if (msg.id && this.callbacks.has(msg.id)) {
          const cb = this.callbacks.get(msg.id);
          this.callbacks.delete(msg.id);
          if (msg.error) cb.reject(msg.error);
          else cb.resolve(msg.result);
        }
      };
    });
  }

  send(method, params = {}) {
    const id = this.id++;
    return new Promise((resolve, reject) => {
      this.callbacks.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    if (this.ws) this.ws.close();
  }
}

async function run() {
  console.log('Launching headless Chrome...');
  const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
  
  if (!fs.existsSync(PROFILE_DIR)) {
    fs.mkdirSync(PROFILE_DIR, { recursive: true });
  }

  const chromeProc = spawn(chromePath, [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${PROFILE_DIR}`,
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    '--window-size=1600,1200'
  ], { detached: false });

  chromeProc.on('error', (err) => {
    console.error('Failed to spawn Chrome:', err);
  });

  // Wait for Chrome port to be ready
  let version = null;
  for (let i = 0; i < 30; i++) {
    await sleep(500);
    try {
      version = await fetchJson(`http://127.0.0.1:${PORT}/json/version`);
      if (version && version.webSocketDebuggerUrl) break;
    } catch (e) {}
  }

  if (!version) {
    chromeProc.kill();
    throw new Error('Chrome did not start debugging port in time');
  }

  console.log('Chrome debugging active:', version.Browser);

  // Connect to browser target
  const browserCdp = new CDPClient(version.webSocketDebuggerUrl);
  await browserCdp.connect();

  // Create new page target
  const { targetId } = await browserCdp.send('Target.createTarget', { url: 'about:blank' });
  const pageWsUrl = `ws://127.0.0.1:${PORT}/devtools/page/${targetId}`;
  
  const pageCdp = new CDPClient(pageWsUrl);
  await pageCdp.connect();

  pageCdp.ws.addEventListener('message', evt => {
    try {
      const msg = JSON.parse(evt.data);
      if (msg.method === 'Runtime.consoleAPICalled') {
        console.log('[BROWSER CONSOLE]', ...msg.params.args.map(a => a.value || JSON.stringify(a)));
      } else if (msg.method === 'Runtime.exceptionThrown') {
        console.error('[BROWSER EXCEPTION]', msg.params.exceptionDetails);
      }
    } catch (e) {}
  });

  await pageCdp.send('Page.enable');
  await pageCdp.send('Runtime.enable');

  console.log('Navigating to:', TARGET_URL);
  await pageCdp.send('Page.navigate', { url: TARGET_URL });

  // Wait for initial load
  await sleep(4000);

  // Helper to evaluate JS in page
  async function evalJs(expr) {
    const res = await pageCdp.send('Runtime.evaluate', {
      expression: expr,
      returnByValue: true,
      awaitPromise: true
    });
    if (res.exceptionDetails) {
      console.error('JS Exception:', res.exceptionDetails);
    }
    return res.result ? res.result.value : null;
  }

  const pageInfo = await evalJs(`
    ({
      title: document.title,
      pageTitle: document.getElementById('pageTitle')?.textContent,
      navButtons: Array.from(document.querySelectorAll('[data-view]')).map(b => b.dataset.view)
    })
  `);
  console.log('Initial page info:', pageInfo);

  // Helper to capture screenshot
  async function snap(filename) {
    const { data } = await pageCdp.send('Page.captureScreenshot', { format: 'png' });
    const fullPath = path.join(ARTIFACT_DIR, filename);
    fs.writeFileSync(fullPath, Buffer.from(data, 'base64'));
    console.log(`Saved screenshot: ${fullPath} (${Math.round(data.length * 0.75 / 1024)} KB)`);
    return fullPath;
  }

  await pageCdp.send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1600, deviceScaleFactor: 1, mobile: false });

  console.log('Switching to Pipeline Runner view...');
  await evalJs(`(() => {
    const btn = document.querySelector('[data-view="pipeline"]');
    if (btn) btn.click();
    else console.error('pipeline button not found');
  })()`);
  await sleep(1500);

  console.log('Expanding Step 1 (Source -> Database)...');
  await evalJs(`(() => {
    const cellHeads = document.querySelectorAll('.notebook-cell-head');
    if (cellHeads.length > 0) cellHeads[0].click();
  })()`);
  await sleep(1500);

  // Scroll step 1 into view
  await evalJs(`(() => {
    const openCell = document.querySelector('.notebook-cell.is-open');
    if (openCell) openCell.scrollIntoView({ behavior: 'instant', block: 'start' });
  })()`);
  await sleep(500);

  // Tab 1: Preview (สรุปผล)
  console.log('Verifying Tab 1: Preview...');
  const t1Res = await evalJs(`(() => {
    const subtabs = document.querySelectorAll('.stage-subtab');
    if (subtabs[0]) {
      subtabs[0].click();
      return subtabs[0].textContent;
    }
    return null;
  })()`);
  console.log('Tab 1 activated:', t1Res);
  await sleep(1000);
  const snap1 = await snap('step1_tab1_preview.png');

  // Tab 2: Input (ข้อมูลนำเข้า)
  console.log('Verifying Tab 2: Input...');
  const t2Res = await evalJs(`(() => {
    const subtabs = document.querySelectorAll('.stage-subtab');
    if (subtabs[1]) {
      subtabs[1].click();
      return subtabs[1].textContent;
    }
    return null;
  })()`);
  console.log('Tab 2 activated:', t2Res);
  await sleep(1000);

  // Click on Fact_Orders.csv row to open samples viewer
  console.log('Clicking Fact_Orders.csv row for sample records...');
  const clickCsvRes = await evalJs(`(() => {
    const rows = Array.from(document.querySelectorAll('.table-row-clickable'));
    const targetRow = rows.find(r => r.textContent.includes('Fact_Orders.csv')) || rows[0];
    if (targetRow) {
      targetRow.click();
      return targetRow.textContent.trim();
    }
    return 'no clickable rows';
  })()`);
  console.log('Clicked CSV row:', clickCsvRes);
  await sleep(1500);

  // Scroll sample records card into view
  await evalJs(`(() => {
    const card = document.querySelector('.csv-samples-card');
    if (card) card.scrollIntoView({ behavior: 'instant', block: 'center' });
  })()`);
  await sleep(1000);
  const snap2 = await snap('step1_tab2_input_csv.png');

  // Tab 3: Process (ขั้นตอนการประมวลผล)
  console.log('Verifying Tab 3: Process Timeline...');
  const t3Res = await evalJs(`(() => {
    const subtabs = document.querySelectorAll('.stage-subtab');
    if (subtabs[2]) {
      subtabs[2].click();
      return subtabs[2].textContent;
    }
    return null;
  })()`);
  console.log('Tab 3 activated:', t3Res);
  await sleep(500);
  await evalJs(`(() => {
    const openCell = document.querySelector('.notebook-cell.is-open');
    if (openCell) openCell.scrollIntoView({ behavior: 'instant', block: 'start' });
  })()`);
  await sleep(1000);
  const snap3 = await snap('step1_tab3_process_timeline.png');

  // Tab 4: Validation (ตรวจสอบข้อมูล)
  console.log('Verifying Tab 4: Validation / Data Quality...');
  const t4Res = await evalJs(`(() => {
    const subtabs = document.querySelectorAll('.stage-subtab');
    if (subtabs[3]) {
      subtabs[3].click();
      return subtabs[3].textContent;
    }
    return null;
  })()`);
  console.log('Tab 4 activated:', t4Res);
  await sleep(500);
  await evalJs(`(() => {
    const openCell = document.querySelector('.notebook-cell.is-open');
    if (openCell) openCell.scrollIntoView({ behavior: 'instant', block: 'start' });
  })()`);
  await sleep(1000);
  const snap4 = await snap('step1_tab4_validation_dq.png');

  // Tab 5: Output (ข้อมูลปลายทาง)
  console.log('Verifying Tab 5: Output (25 ER1 tables)...');
  const t5Res = await evalJs(`(() => {
    const subtabs = document.querySelectorAll('.stage-subtab');
    if (subtabs[4]) {
      subtabs[4].click();
      return subtabs[4].textContent;
    }
    return null;
  })()`);
  console.log('Tab 5 activated:', t5Res);
  await sleep(1000);

  // Click Fact_Orders to load live Neon evidence
  console.log('Clicking Fact_Orders in Output tab to load live Neon evidence...');
  const clickNeonRes = await evalJs(`(() => {
    const rows = Array.from(document.querySelectorAll('.table-row-clickable'));
    const targetRow = rows.find(r => r.textContent.includes('Fact_Orders') && !r.textContent.includes('Fact_Orders.csv')) || rows[0];
    if (targetRow) {
      targetRow.click();
      return targetRow.textContent.trim();
    }
    return 'no clickable rows in output tab';
  })()`);
  console.log('Clicked Neon table row:', clickNeonRes);

  // Wait 4 seconds for Neon API response and rendering
  await sleep(4000);

  // Scroll live Neon pane into view
  await evalJs(`(() => {
    const pane = document.querySelector('.live-neon-pane');
    if (pane) pane.scrollIntoView({ behavior: 'instant', block: 'center' });
  })()`);
  await sleep(1000);
  const snap5 = await snap('step1_tab5_output_neon.png');

  console.log('All 5 screenshots captured successfully!');

  // Cleanup
  pageCdp.close();
  browserCdp.close();
  chromeProc.kill();
  process.exit(0);
}

run().catch(err => {
  console.error('Error during verification:', err);
  process.exit(1);
});
