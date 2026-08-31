#!/usr/bin/env node
/**
 * Scribunto Console Client
 * 
 * Sends Lua code to a running scribunto_daemon.js and prints the output.
 * 
 * Usage:
 *   node scribunto_console.js --script hello.lua
 *   echo 'print(1+1)' | node scribunto_console.js
 *   node scribunto_console.js --script hello.lua --json
 *   node scribunto_console.js --config config.ini --script hello.lua
 */

const fs = require('fs');
const http = require('http');
const path = require('path');
const os = require('os');
const url = require('url');

const DEFAULT_CONFIG = {
  daemonPort: 0, // will be discovered via /status
  wikiBaseUrl: 'https://wiki.warframe.com'
};

let config = { ...DEFAULT_CONFIG };

function loadConfig(configPath = 'config.ini') {
  if (!fs.existsSync(configPath)) {
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

    return parsedConfig;
  } catch (error) {
    console.error(`Error loading config: ${error.message}`);
    return { ...DEFAULT_CONFIG };
  }
}

function findDaemonPort() {
  return new Promise((resolve, reject) => {
    const pidFile = path.join(os.tmpdir(), 'scribunto_daemon.pid');

    if (fs.existsSync(pidFile)) {
      try {
        const info = JSON.parse(fs.readFileSync(pidFile, 'utf8'));
        const req = http.request({
          hostname: '127.0.0.1',
          port: info.port,
          path: '/status',
          method: 'GET',
          timeout: 2000
        }, (res) => {
          let data = '';
          res.on('data', chunk => { data += chunk; });
          res.on('end', () => {
            try {
              const status = JSON.parse(data);
              if (status.ready) {
                resolve(info.port);
              } else {
                reject(new Error('Daemon process found but not ready. Is it still running?'));
              }
            } catch (err) {
              reject(new Error('Invalid daemon status response'));
            }
          });
        });

        req.on('error', () => {
          reject(new Error('Could not connect to daemon. Is it running?'));
        });

        req.end();
      } catch (err) {
        reject(new Error('Could not read daemon PID file'));
      }
    } else {
      reject(new Error('Could not connect to daemon. Is it running?'));
    }
  });
}

function executeOnDaemon(port, code) {
  return new Promise((resolve, reject) => {
    const requestBody = JSON.stringify({ code });
    const req = http.request({
      hostname: '127.0.0.1',
      port: port,
      path: '/execute',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(requestBody)
      }
    }, (res) => {
      let data = '';
      res.on('data', chunk => { data += chunk; });
      res.on('end', () => {
        try {
          const result = JSON.parse(data);
          if (result.error) {
            reject(new Error(result.error));
          } else {
            resolve(result.output);
          }
        } catch (err) {
          reject(new Error(`Failed to parse daemon response: ${err.message}`));
        }
      });
    });

    req.on('error', reject);
    req.write(requestBody);
    req.end();
  });
}

function tryParseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

async function main() {
  const args = process.argv.slice(2);
  let configPath = 'config.ini';
  let scriptFile = null;
  let jsonOutput = false;

  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--config' && args[i + 1]) {
      configPath = args[++i];
    } else if (args[i] === '--script' && args[i + 1]) {
      scriptFile = args[++i];
    } else if (args[i] === '--json') {
      jsonOutput = true;
    }
  }

  config = loadConfig(configPath);

  let luaCode;
  if (scriptFile) {
    if (!fs.existsSync(scriptFile)) {
      console.error(`Error: Script file not found: ${scriptFile}`);
      process.exit(1);
    }
    luaCode = fs.readFileSync(scriptFile, 'utf8');
    // Scribunto console wraps input in a function, so trailing `return` is invalid
    // Strip trailing empty lines, then strip trailing `return` lines
    let lines = luaCode.split('\n');
    while (lines.length > 0 && lines[lines.length - 1].trim() === '') {
      lines.pop();
    }
    while (lines.length > 0 && lines[lines.length - 1].trim().match(/^return\b/)) {
      lines.pop();
    }
    luaCode = lines.join('\n');
  } else if (!process.stdin.isTTY) {
    let chunks = '';
    for await (const chunk of process.stdin) {
      chunks += chunk;
    }
    luaCode = chunks;
  } else {
    console.error('Usage:');
    console.error('  node scribunto_console.js --script hello.lua');
    console.error('  echo "print(1+1)" | node scribunto_console.js');
    console.error('  node scribunto_console.js --script hello.lua --json');
    process.exit(1);
  }

  if (!luaCode.trim()) {
    console.error('Error: No Lua code provided');
    process.exit(1);
  }

  try {
    const port = await findDaemonPort();
    const output = await executeOnDaemon(port, luaCode);

    if (jsonOutput) {
      const parsed = tryParseJson(output);
      if (parsed !== null) {
        console.log(JSON.stringify(parsed, null, 2));
      } else {
        console.log(output);
      }
    } else {
      console.log(output);
    }
  } catch (error) {
    console.error(`Error: ${error.message}`);
    process.exit(1);
  }
}

main().catch(err => {
  console.error(`Fatal error: ${err.message}`);
  process.exit(1);
});
