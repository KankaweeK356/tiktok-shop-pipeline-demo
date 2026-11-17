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

  console.log('Navigating and letting app initialize...');
  await send('Page.navigate', { url: TARGET_URL });
  await new Promise(r => setTimeout(r, 4000));

  const stateCheck = await send('Runtime.evaluate', {
    expression: `({ hasData: Boolean(window.__appState?.data), view: window.__appState?.view })`,
    returnByValue: true
  });
  console.log('App state after load:', JSON.stringify(stateCheck.result.value));

  // Capture Business view top
  await send('Runtime.evaluate', { expression: 'window.scrollTo(0, 0)' });
  await new Promise(r => setTimeout(r, 1000));
  let snap = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(ARTIFACT_DIR, 'business_decision_master_fix_top.png'), Buffer.from(snap.data, 'base64'));
  console.log('Saved top screenshot');

  // Capture Business view bottom
  await send('Runtime.evaluate', { expression: 'window.scrollTo(0, 750)' });
  await new Promise(r => setTimeout(r, 1000));
  snap = await send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(ARTIFACT_DIR, 'business_decision_master_fix_bottom.png'), Buffer.from(snap.data, 'base64'));
  console.log('Saved bottom screenshot');

  ws.close();
})();
