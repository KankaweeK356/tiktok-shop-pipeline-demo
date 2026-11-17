const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');

const ARTIFACT_DIR = 'C:\\Users\\kankawee.k\\.gemini\\antigravity\\brain\\247e4374-55e6-40c9-9b7d-8a1a8705b6c5';
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
        try { resolve(JSON.parse(data)); } catch (e) { reject(e); }
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

  async eval(expression) {
    const res = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    return res.result ? res.result.value : null;
  }

  async screenshot(filePath, clip = null) {
    const params = { format: 'png' };
    if (clip) params.clip = clip;
    const res = await this.send('Page.captureScreenshot', params);
    fs.writeFileSync(filePath, Buffer.from(res.data, 'base64'));
    console.log('Saved screenshot: ' + filePath);
  }
}

async function main() {
  console.log('Connecting to Chrome...');
  let versionInfo = null;
  try {
    versionInfo = await fetchJson('http://127.0.0.1:' + PORT + '/json/version');
  } catch (_e) {}

  if (!versionInfo) {
    const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
    const profileDir = path.join(ARTIFACT_DIR, 'scratch', 'chrome-profile');
    const chromeProc = spawn(chromePath, [
      '--remote-debugging-port=' + PORT,
      '--headless=new',
      '--disable-gpu',
      '--no-first-run',
      '--no-default-browser-check',
      '--user-data-dir=' + profileDir,
      'about:blank'
    ], { detached: true, stdio: 'ignore' });
    chromeProc.unref();

    for (let i = 0; i < 30; i++) {
      await sleep(500);
      try {
        versionInfo = await fetchJson('http://127.0.0.1:' + PORT + '/json/version');
        if (versionInfo) break;
      } catch (_e) {}
    }
  }

  if (!versionInfo) {
    console.error('Failed to connect to Chrome');
    process.exit(1);
  }

  const targets = await fetchJson('http://127.0.0.1:' + PORT + '/json/list');
  const pageTarget = targets.find(t => t.type === 'page') || targets[0];
  const cdp = new CDPClient(pageTarget.webSocketDebuggerUrl);
  await cdp.connect();
  console.log('Connected to CDP');

  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: 1440,
    height: 900,
    deviceScaleFactor: 1,
    mobile: false
  });

  console.log('Navigating to ' + TARGET_URL + '...');
  await cdp.send('Page.navigate', { url: TARGET_URL });
  await sleep(4000);

  // Poll for deployment update: check if Rule IDs or Assumed Demand Lift are present
  let deployed = false;
  for (let attempt = 1; attempt <= 20; attempt++) {
    const check = await cdp.eval(`
      (() => {
        const text = document.body.innerText || "";
        const hasRule = text.includes("[R01") || text.includes("R01-REV");
        const hasLift = text.includes("Assumed Demand Lift") || text.includes("สมมติฐานยอดขายที่เพิ่มขึ้น");
        return { hasRule, hasLift, length: text.length };
      })()
    `);
    console.log('Poll attempt ' + attempt + ':', JSON.stringify(check));
    if (check && (check.hasRule || check.hasLift)) {
      deployed = true;
      console.log('New deployment verified on Vercel!');
      break;
    }
    await sleep(3000);
    await cdp.send('Page.reload', { ignoreCache: true });
    await sleep(2000);
  }

  // 1. Capture Business Overview (Top & Bottom)
  console.log('Capturing Business Dashboard screenshots...');
  await cdp.eval('window.scrollTo(0, 0);');
  await sleep(1000);
  await cdp.screenshot(path.join(ARTIFACT_DIR, 'business_decision_master_fix_top.png'));

  await cdp.eval('window.scrollTo(0, 600);');
  await sleep(1000);
  await cdp.screenshot(path.join(ARTIFACT_DIR, 'business_decision_master_fix_bottom.png'));

  // 2. Navigate to Pipeline View and capture February Viewed State
  console.log('Navigating to Pipeline view...');
  await cdp.eval(`
    (() => {
      const navBtn = Array.from(document.querySelectorAll('.app-nav-button')).find(b => b.innerText.includes('ทดสอบการนำเข้า'));
      if (navBtn) navBtn.click();
    })()
  `);
  await sleep(3000);

  // Click February month chip
  console.log('Clicking February chip...');
  await cdp.eval(`
    (() => {
      const febChip = Array.from(document.querySelectorAll('.month-chip')).find(c => c.innerText.includes('ก.พ.'));
      if (febChip) febChip.click();
    })()
  `);
  await sleep(2000);

  await cdp.eval('window.scrollTo(0, 0);');
  await sleep(1000);
  await cdp.screenshot(path.join(ARTIFACT_DIR, 'pipeline_february_viewed_state.png'));

  console.log('All verification screenshots captured successfully!');
}

main().catch(console.error);
