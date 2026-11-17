const { spawn } = require('child_process');
const http = require('http');
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

  close() {
    if (this.ws) this.ws.close();
  }
}

async function run() {
  const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
  const chromeProc = spawn(chromePath, [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${PROFILE_DIR}`,
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check'
  ], { detached: false });

  let version = null;
  for (let i = 0; i < 30; i++) {
    await sleep(500);
    try {
      version = await fetchJson(`http://127.0.0.1:${PORT}/json/version`);
      if (version?.webSocketDebuggerUrl) break;
    } catch (e) {}
  }

  const browserCdp = new CDPClient(version.webSocketDebuggerUrl);
  await browserCdp.connect();

  const { targetId } = await browserCdp.send('Target.createTarget', { url: 'about:blank' });
  const pageWsUrl = `ws://127.0.0.1:${PORT}/devtools/page/${targetId}`;
  
  const pageCdp = new CDPClient(pageWsUrl);
  await pageCdp.connect();

  pageCdp.ws.addEventListener('message', evt => {
    try {
      const msg = JSON.parse(evt.data);
      if (msg.method === 'Runtime.consoleAPICalled') {
        console.log('[BROWSER CONSOLE]', msg.params.type, ...msg.params.args.map(a => a.value || JSON.stringify(a)));
      } else if (msg.method === 'Runtime.exceptionThrown') {
        console.error('[BROWSER EXCEPTION]', msg.params.exceptionDetails.text, msg.params.exceptionDetails.exception?.description);
      }
    } catch (e) {}
  });

  await pageCdp.send('Page.enable');
  await pageCdp.send('Runtime.enable');

  console.log('Navigating to:', TARGET_URL);
  await pageCdp.send('Page.navigate', { url: TARGET_URL });
  await sleep(4000);

  const debugResult = await pageCdp.send('Runtime.evaluate', {
    expression: `(() => {
      try {
        const appEl = document.querySelector('#app');
        return {
          appChildren: appEl ? appEl.children.length : 0,
          appHtmlSnippet: appEl ? appEl.innerHTML.substring(0, 300) : null,
          decisionRoot: Boolean(document.querySelector('.decision-dashboard-root')),
          stateData: Boolean(window.state?.data),
          stateView: window.state?.view,
          warehouseStatus: window.state?.warehouseStatus
        };
      } catch (err) {
        return { error: err.message, stack: err.stack };
      }
    })()`,
    returnByValue: true
  });

  console.log('Debug result on page load:', debugResult.result?.value);

  // Now trigger setView('business') manually
  const triggerRes = await pageCdp.send('Runtime.evaluate', {
    expression: `(() => {
      try {
        const btn = document.querySelector('[data-view="business"]');
        if (btn) btn.click();
        return {
          clicked: true,
          appChildren: document.querySelector('#app')?.children.length,
          decisionRoot: Boolean(document.querySelector('.decision-dashboard-root')),
          innerSnippet: document.querySelector('#app')?.innerHTML.substring(0, 300)
        };
      } catch (err) {
        return { error: err.message, stack: err.stack };
      }
    })()`,
    returnByValue: true
  });
  console.log('After setView("business"):', triggerRes.result?.value);

  pageCdp.close();
  browserCdp.close();
  chromeProc.kill();
}

run().catch(console.error);
