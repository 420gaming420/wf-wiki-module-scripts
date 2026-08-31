#!/usr/bin/env node
/**
 * Scribunto Debug Console Daemon
 * 
 * Launches a persistent headless Chromium browser connected to the
 * WARFRAME Wiki Scribunto Debug Console and exposes an HTTP API
 * for executing Lua code.
 * 
 * Usage:
 *   node scribunto_daemon.js [--config config.ini]
 * 
 * API:
 *   POST /execute  {"code": "lua code here"}  →  {"output": "...", "error": null}
 *   GET  /status   →  {"ready": true, "idle_seconds": 0}
 */

const puppeteer = require('puppeteer');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
const url = require('url');

const DEFAULT_CONFIG = {
  wikiBaseUrl: 'https://wiki.warframe.com',
  timeoutMs: 60000,
  browserTimeout: 30000,
  idleTimeoutMs: 3600000, // 60 minutes
  port: 0 // random unused port
};

let config = { ...DEFAULT_CONFIG };
let browser = null;
let page = null;
let lastActivity = Date.now();
let idleTimer = null;

function loadConfig(configPath = 'config.ini') {
  if (!fs.existsSync(configPath)) {
    console.log(`Warning: Config file not found at ${configPath}, using defaults`);
    return { ...DEFAULT_CONFIG };
  }

  try {
    const content = fs.readFileSync(configPath, 'utf8');
    const lines = content.split('\n');
    const parsedConfig = { ...DEFAULT_CONFIG };

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;

      const match = trimmed.match(/^([a-zA-Z_]+)\s*=\s*(.+)$/);
      if (match) {
        const key = match[1];
        const value = match[2].trim();

        if (value === 'true' || value === '1') {
          parsedConfig[key] = true;
        } else if (value === 'false' || value === '0') {
          parsedConfig[key] = false;
        } else if (!isNaN(value) && value !== '') {
          parsedConfig[key] = parseFloat(value);
        } else {
          parsedConfig[key] = value;
        }
      }
    }

    console.log('Loaded configuration from config.ini');
    return parsedConfig;
  } catch (error) {
    console.error(`Error loading config: ${error.message}`);
    return { ...DEFAULT_CONFIG };
  }
}

async function initBrowser() {
  console.log('Launching headless browser...');
  browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  page = await browser.newPage();
  await page.setUserAgent(
    'puppeteer_wf-wiki-module-mirror (https://github.com/420gaming420/wf-wiki-module-scripts)'
  );

  const editUrl = `${config.wikiBaseUrl}/w/Module:Sandbox/ScribuntoDebugConsole?action=edit`;
  console.log(`  Navigating to: ${editUrl}`);
  await page.goto(editUrl, {
    waitUntil: 'networkidle0',
    timeout: config.browserTimeout
  });
  await page.waitForSelector('#mw-scribunto-input', { timeout: 10000 });

  console.log('Browser ready.');
}

async function clearConsole() {
  const clearButton = await page.$('form button[type="button"], input[type="button"]');
  if (clearButton) {
    await clearButton.click();
  }
  await new Promise(resolve => setTimeout(resolve, 100));
}

async function executeLua(luaCode) {
  await page.evaluate((code) => {
    const el = document.getElementById('mw-scribunto-input');
    if (el) {
      el.value = code;
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }, luaCode);

  await page.keyboard.press('Enter');
  await new Promise(resolve => setTimeout(resolve, 500));

  await page.waitForSelector('#mw-scribunto-output', { timeout: 30000 });

  const outputInfo = await page.evaluate(() => {
    const outputEl = document.getElementById('mw-scribunto-output');
    const printEl = outputEl?.querySelector('.mw-scribunto-print');
    const errorEl = outputEl?.querySelector('.mw-scribunto-error');
    return {
      printFound: !!printEl,
      errorFound: !!errorEl,
      errorText: errorEl?.textContent?.substring(0, 200),
      printText: printEl?.textContent?.substring(0, 200)
    };
  });

  if (outputInfo.errorFound) {
    throw new Error(`Lua error: ${outputInfo.errorText}`);
  }

  await page.waitForSelector('.mw-scribunto-print', { timeout: 15000 });
  await new Promise(resolve => setTimeout(resolve, 1000));

  const output = await page.evaluate(() => {
    const printEl = document.querySelector('.mw-scribunto-print');
    if (printEl) {
      return { text: printEl.textContent, from: 'print-div' };
    }

    const outputEl = document.getElementById('mw-scribunto-output');
    const allText = outputEl?.textContent || '';
    const lines = allText.split('\n').filter(l => l.trim());
    for (let i = lines.length - 1; i >= 0; i--) {
      const line = lines[i].trim();
      if (line.startsWith('{') || line.startsWith('[')) {
        return { text: line, from: 'fallback' };
      }
    }
    return { text: null, from: 'fallback' };
  });

  if (!output.text) {
    throw new Error('No output found in console');
  }

  return output.text;
}

async function resetIdleTimer() {
  if (idleTimer) {
    clearTimeout(idleTimer);
  }
  idleTimer = setTimeout(() => {
    console.log('Idle timeout reached (60 minutes). Shutting down.');
    shutdown();
  }, config.idleTimeoutMs);
}

async function shutdown() {
  console.log('Shutting down daemon...');
  if (idleTimer) clearTimeout(idleTimer);
  const pidFile = path.join(os.tmpdir(), 'scribunto_daemon.pid');
  try { fs.unlinkSync(pidFile); } catch {}
  if (page) await page.close().catch(() => {});
  if (browser) await browser.close().catch(() => {});
  process.exit(0);
}

async function handleExecute(req, res) {
  let body = '';
  req.on('data', chunk => { body += chunk; });
  req.on('end', async () => {
    try {
      const { code } = JSON.parse(body);
      if (!code) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Missing "code" field' }));
        return;
      }

      lastActivity = Date.now();
      resetIdleTimer();

      await clearConsole();
      const output = await executeLua(code);
      await clearConsole();

      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ output, error: null }));
    } catch (error) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ output: null, error: error.message }));
    }
  });
}

async function handleStatus(req, res) {
  const idleSeconds = Math.floor((Date.now() - lastActivity) / 1000);
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ ready: !!browser, idle_seconds: idleSeconds }));
}

async function main() {
  const args = process.argv.slice(2);
  let configPath = 'config.ini';
  const configIndex = args.indexOf('--config');
  if (configIndex !== -1 && args[configIndex + 1]) {
    configPath = args[configIndex + 1];
    args.splice(configIndex, 2);
  }

  config = loadConfig(configPath);

  await initBrowser();

  const server = http.createServer((req, res) => {
    const parsed = url.parse(req.url, true);
    lastActivity = Date.now();
    resetIdleTimer();

    if (req.method === 'POST' && parsed.pathname === '/execute') {
      handleExecute(req, res);
    } else if (req.method === 'GET' && parsed.pathname === '/status') {
      handleStatus(req, res);
    } else {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Not found' }));
    }
  });

  server.listen(0, '127.0.0.1', async () => {
    const port = server.address().port;
    const pidFile = path.join(os.tmpdir(), 'scribunto_daemon.pid');
    fs.writeFileSync(pidFile, JSON.stringify({ port, pid: process.pid }));
    console.log(`Daemon listening on http://localhost:${port}`);
    console.log('Press Ctrl+C to stop.');
    console.log('');
    console.log('Usage:');
    console.log('  echo "print(1+1)" | node scribunto_console.js');
    console.log('  node scribunto_console.js --script hello.lua');
    console.log('  node scribunto_console.js --script hello.lua --json');
  });

  process.on('SIGINT', () => { console.log('\nReceived SIGINT'); shutdown(); });
  process.on('SIGTERM', () => { console.log('\nReceived SIGTERM'); shutdown(); });
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
