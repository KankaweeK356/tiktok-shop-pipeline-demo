const http = require('http');
const fs = require('fs');
const path = require('path');

const ARTIFACT_DIR = 'C:\\Users\\kankawee.k\\.gemini\\antigravity\\brain\\247e4374-55e6-40c9-9b7d-8a1a8705b6c5';
const TARGET_URL = 'https://tiktok-shop-mlops-dashboard-git-feature-classroom-dea39b-newja.vercel.app';
const PORT = 9222;

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

(async () => {
  const targets = await fetchJson('http://127.0.0.1:' + PORT + '/json/list');
  const pageTarget = targets.find(t => t.type === 'page') || targets[0];
  const ws = new WebSocket(pageTarget.webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);

  let id = 1;
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const curId = id++;
    const handler = (evt) => {
      const msg = JSON.parse(evt.data);
      if (msg.id === curId) {
        ws.removeEventListener('message', handler);
        resolve(msg.result);
      }
    };
    ws.addEventListener('message', handler);
    ws.send(JSON.stringify({ id: curId, method, params }));
  });

  console.log('Navigating and hard reloading...');
  await send('Page.navigate', { url: TARGET_URL });
  await new Promise(r => setTimeout(r, 4000));
  await send('Page.reload', { ignoreCache: true });
  await new Promise(r => setTimeout(r, 4000));

  // 1. Capture Progressive Single-Month (January only)
  console.log('1. Capturing Progressive Single-Month Top & Bottom...');
  await send('Runtime.evaluate', { expression: `
    (() => {
      const s = window.__appState;
      if (!s) return;
      s.view = 'business';
      s.currentCycleRuns = [
        { run_id: "RUN1-202601", run_type: "RUN1", source_batch: "initial", batch: "initial", status: "SUCCEEDED", created_at: "2026-11-17T08:00:00Z" }
      ];
      s.nextSourceBatch = "incremental_01";
      if (typeof window.__appRender === 'function') window.__appRender();
      window.scrollTo(0, 0);
    })()
  ` });
  await new Promise(r => setTimeout(r, 1200));
  let snap = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(ARTIFACT_DIR, 'business_progressive_single_month_top.png'), Buffer.from(snap.data, 'base64'));

  await send('Runtime.evaluate', { expression: 'window.scrollTo(0, 750)' });
  await new Promise(r => setTimeout(r, 1200));
  snap = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(ARTIFACT_DIR, 'business_progressive_single_month_bottom.png'), Buffer.from(snap.data, 'base64'));

  // 2. Capture Progressive Multi-Month (January + February published)
  console.log('2. Capturing Progressive Multi-Month (Jan + Feb)...');
  await send('Runtime.evaluate', { expression: `
    (() => {
      const s = window.__appState;
      if (!s) return;
      s.view = 'business';
      s.currentCycleRuns = [
        { run_id: "RUN1-202601", run_type: "RUN1", source_batch: "initial", batch: "initial", status: "SUCCEEDED", created_at: "2026-11-17T08:00:00Z" },
        { run_id: "RUN2-202602", run_type: "RUN2", source_batch: "incremental_01", batch: "incremental_01", status: "SUCCEEDED", created_at: "2026-11-17T08:30:00Z" }
      ];
      s.nextSourceBatch = "incremental_02";
      if (typeof window.__appRender === 'function') window.__appRender();
      window.scrollTo(0, 0);
    })()
  ` });
  await new Promise(r => setTimeout(r, 1200));
  snap = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(ARTIFACT_DIR, 'business_progressive_multi_month_top.png'), Buffer.from(snap.data, 'base64'));

  // 3. Capture Pipeline View (February Completed, March Executing)
  console.log('3. Capturing Pipeline View (February Completed, March Executing)...');
  await send('Runtime.evaluate', { expression: `
    (() => {
      const s = window.__appState;
      if (!s) return;
      s.view = 'pipeline';
      s.nextSourceBatch = "incremental_02";
      s.viewedBatch = "incremental_01";
      s.notebookBatch = "incremental_01";
      s.notebookStage = "ingest";
      s.batchResults["incremental_01"] = {
        ingest: { evidence: { output: { records: 280 } }, runId: "RUN2-202602" },
        extract: { evidence: { output: { parquet_files: 21 } }, runId: "RUN2-202602" },
        transform: { evidence: { output: { quality: "PASS" } }, runId: "RUN2-202602" },
        load: { evidence: { output: { warehouse_tables: 8 } }, runId: "RUN2-202602" },
        validate: { evidence: { output: { reconcile: "PASS" } }, runId: "RUN2-202602" }
      };
      if (typeof window.__appRender === 'function') window.__appRender();
      window.scrollTo(0, 500);
    })()
  ` });
  await new Promise(r => setTimeout(r, 1200));
  snap = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(ARTIFACT_DIR, 'pipeline_february_stages_detail.png'), Buffer.from(snap.data, 'base64'));

  console.log('All verification screenshots captured cleanly!');
  ws.close();
})();
