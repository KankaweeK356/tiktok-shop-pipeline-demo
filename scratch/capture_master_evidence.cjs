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
  console.log('Checking Chrome connection...');
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

  // Reload cache to get latest commit
  await cdp.send('Page.reload', { ignoreCache: true });
  await sleep(3000);

  // 1. Capture Business Overview Top
  console.log('Capturing Business Dashboard Top...');
  await cdp.eval(`
    if (window.__appState) {
      window.__appState.view = 'business';
      if (typeof window.__appRenderBusiness === 'function') window.__appRenderBusiness();
    }
    window.scrollTo(0, 0);
  `);
  await sleep(1500);
  await cdp.screenshot(path.join(ARTIFACT_DIR, 'business_decision_master_fix_top.png'));

  // 2. Capture Business Overview Bottom (Scenario Studio + Rule IDs)
  console.log('Capturing Business Dashboard Bottom...');
  await cdp.eval('window.scrollTo(0, 650);');
  await sleep(1500);
  await cdp.screenshot(path.join(ARTIFACT_DIR, 'business_decision_master_fix_bottom.png'));

  // 3. Switch to Pipeline View and inspect February
  console.log('Simulating and capturing Pipeline February state...');
  await cdp.eval(`
    (() => {
      const s = window.__appState;
      if (!s) return;
      s.view = 'pipeline';
      // Simulate that initial has run and February incremental_01 has completed
      s.currentCycleRuns = [
        { run_id: "RUN1-202601", run_type: "RUN1", source_batch: "initial", batch: "initial", status: "SUCCEEDED", created_at: "2026-11-17T08:00:00Z" },
        { run_id: "RUN2-202602", run_type: "RUN2", source_batch: "incremental_01", batch: "incremental_01", status: "SUCCEEDED", created_at: "2026-11-17T08:30:00Z" }
      ];
      s.nextSourceBatch = "incremental_02"; // March is active execution pointer
      s.viewedBatch = "incremental_01";     // User is clicking February to view history
      s.notebookBatch = "incremental_01";
      s.notebookStage = "ingest";
      // Give February a real stage result
      s.batchResults["incremental_01"] = {
        ingest: { evidence: { output: { records: 280 } }, runId: "RUN2-202602" },
        extract: { evidence: { output: { parquet_files: 21 } }, runId: "RUN2-202602" },
        transform: { evidence: { output: { quality: "PASS" } }, runId: "RUN2-202602" },
        load: { evidence: { output: { warehouse_tables: 8 } }, runId: "RUN2-202602" },
        validate: { evidence: { output: { reconcile: "PASS" } }, runId: "RUN2-202602" }
      };
      if (typeof window.__appRender === 'function') window.__appRender();
      window.scrollTo(0, 0);
    })()
  `);
  await sleep(1500);
  await cdp.screenshot(path.join(ARTIFACT_DIR, 'pipeline_february_stage_view.png'));

  console.log('All evidence captured successfully!');
}

main().catch(console.error);
