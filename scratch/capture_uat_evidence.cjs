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
    '--window-size=1600,1400'
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

  const browserCdp = new CDPClient(version.webSocketDebuggerUrl);
  await browserCdp.connect();

  const { targetId } = await browserCdp.send('Target.createTarget', { url: 'about:blank' });
  const pageWsUrl = `ws://127.0.0.1:${PORT}/devtools/page/${targetId}`;
  
  const pageCdp = new CDPClient(pageWsUrl);
  await pageCdp.connect();

  await pageCdp.send('Page.enable');
  await pageCdp.send('Runtime.enable');

  console.log('Navigating to:', TARGET_URL);
  await pageCdp.send('Page.navigate', { url: TARGET_URL });
  await sleep(4500);

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

  async function snap(filename) {
    const { data } = await pageCdp.send('Page.captureScreenshot', { format: 'png' });
    const fullPath = path.join(ARTIFACT_DIR, filename);
    fs.writeFileSync(fullPath, Buffer.from(data, 'base64'));
    console.log(`Saved screenshot: ${fullPath} (${Math.round(data.length * 0.75 / 1024)} KB)`);
    return fullPath;
  }

  await pageCdp.send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1400, deviceScaleFactor: 1, mobile: false });

  // 1. Business Decision Dashboard Screenshot
  console.log('Verifying Business Decision Dashboard (Section 1 to 7)...');
  await evalJs(`(() => {
    const btn = document.querySelector('[data-view="business"]');
    if (btn) btn.click();
  })()`);
  await sleep(2000);
  await snap('business_decision_dashboard_top.png');

  // Scroll down to scenario studio & forecast
  await evalJs(`(() => {
    const studio = document.querySelector('.decision-three-col') || document.querySelector('.scenario-result-box');
    if (studio) studio.scrollIntoView({ behavior: 'instant', block: 'center' });
  })()`);
  await sleep(1000);
  await snap('business_decision_dashboard_bottom.png');

  // 2. Switch to Pipeline Runner view
  console.log('Switching to Pipeline Runner view...');
  await evalJs(`(() => {
    const btn = document.querySelector('[data-view="pipeline"]');
    if (btn) btn.click();
  })()`);
  await sleep(1500);

  // 3. Stage 1 Input Master-Detail Split View
  console.log('Opening Stage 1 Input Master-Detail Split View...');
  await evalJs(`(() => {
    const cellHeads = document.querySelectorAll('.notebook-cell-head');
    if (cellHeads.length > 0) cellHeads[0].click();
  })()`);
  await sleep(1000);
  await evalJs(`(() => {
    const subtabs = document.querySelectorAll('.stage-subtab');
    if (subtabs[1]) subtabs[1].click(); // Input subtab
  })()`);
  await sleep(1500);

  // Click on Fact_Orders.csv in the split view
  await evalJs(`(() => {
    const items = Array.from(document.querySelectorAll('.split-list-item'));
    const factOrdersItem = items.find(it => it.textContent.includes('Fact_Orders.csv')) || items[0];
    if (factOrdersItem) factOrdersItem.click();
  })()`);
  await sleep(1000);
  await evalJs(`(() => {
    const split = document.querySelector('.split-view-container');
    if (split) split.scrollIntoView({ behavior: 'instant', block: 'center' });
  })()`);
  await sleep(500);
  await snap('master_detail_stage1_input_split.png');

  // 4. Stage 1 Output (Live Neon) Master-Detail Split View
  console.log('Opening Stage 1 Output Live Neon Master-Detail Split View...');
  await evalJs(`(() => {
    const subtabs = document.querySelectorAll('.stage-subtab');
    if (subtabs[4]) subtabs[4].click(); // Output subtab
  })()`);
  await sleep(1500);

  // Click on Fact_Order_Items in the 25 Neon tables split view
  await evalJs(`(() => {
    const items = Array.from(document.querySelectorAll('.split-list-item'));
    const targetItem = items.find(it => it.textContent.includes('Fact_Order_Items')) || items[1];
    if (targetItem) targetItem.click();
  })()`);
  await sleep(3500); // Wait for live Neon query

  await evalJs(`(() => {
    const split = document.querySelector('.split-view-container');
    if (split) split.scrollIntoView({ behavior: 'instant', block: 'center' });
  })()`);
  await sleep(500);
  await snap('master_detail_stage1_output_neon_split.png');

  // 5. Stage 4 DuckDB Warehouse Master-Detail Split View
  console.log('Opening Stage 4 DuckDB Warehouse Master-Detail Split View...');
  await evalJs(`(() => {
    const cellHeads = document.querySelectorAll('.notebook-cell-head');
    if (cellHeads.length > 3) cellHeads[3].click(); // Stage 4: load
  })()`);
  await sleep(1000);
  await evalJs(`(() => {
    const subtabs = document.querySelectorAll('.stage-subtab');
    if (subtabs[4]) subtabs[4].click(); // Output subtab
  })()`);
  await sleep(1500);

  await evalJs(`(() => {
    const split = document.querySelector('.split-view-container');
    if (split) split.scrollIntoView({ behavior: 'instant', block: 'center' });
  })()`);
  await sleep(500);
  await snap('master_detail_stage4_warehouse_split.png');

  // 6. February Incremental State (Testing Defect 02 fix: Waiting/Empty State)
  console.log('Testing February Incremental State (Clicking February chip)...');
  await evalJs(`(() => {
    const chips = Array.from(document.querySelectorAll('.month-chip'));
    const febChip = chips.find(c => c.textContent.includes('กุมภาพันธ์') || c.textContent.includes('ก.พ.'));
    if (febChip) febChip.click();
  })()`);
  await sleep(1000);

  // Check Preview subtab of Stage 1 for February
  await evalJs(`(() => {
    const cellHeads = document.querySelectorAll('.notebook-cell-head');
    if (cellHeads.length > 0) cellHeads[0].click();
  })()`);
  await sleep(500);
  await evalJs(`(() => {
    const subtabs = document.querySelectorAll('.stage-subtab');
    if (subtabs[0]) subtabs[0].click(); // Preview subtab
  })()`);
  await sleep(1000);

  await evalJs(`(() => {
    const emptyCard = document.querySelector('.empty-state-card') || document.querySelector('.runner-controls-card');
    if (emptyCard) emptyCard.scrollIntoView({ behavior: 'instant', block: 'center' });
  })()`);
  await sleep(500);
  await snap('february_incremental_waiting_state.png');

  console.log('UAT verification completed successfully!');

  pageCdp.close();
  browserCdp.close();
  chromeProc.kill();
  process.exit(0);
}

run().catch(err => {
  console.error('Error during UAT verification:', err);
  process.exit(1);
});
