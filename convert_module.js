#!/usr/bin/env node
/**
 * WARFRAME Wiki Module to JSON Converter
 * Uses Scribunto Debug Console via Puppeteer
 * 
 * Usage:
 *   node convert_module.js <Module:Name/path> [output.json]
 *   node convert_module.js --batch --pages stale_modules.json
 *   node convert_module.js --config config.ini --batch --pages stale_modules.json
 */

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

// Default configuration
const DEFAULT_CONFIG = {
  wikiBaseUrl: 'https://wiki.warframe.com',
  rateLimitMs: 1000,
  timeoutMs: 60000,
  maxRetries: 3,
  retryDelayMs: 2000,
  browserTimeout: 30000,
  outputDir: 'data/json',
  metadataDir: 'data/json',
  ignoreModulesFile: 'ignore_modules.json',
  logDir: 'data/logs'
};

let config = { ...DEFAULT_CONFIG };

/**
 * Load configuration from config.ini
 */
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
        
        // Convert to appropriate type
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

/**
 * Load ignored modules from ignore_modules.json
 */
function loadIgnoredModules(ignorePath) {
  if (!fs.existsSync(ignorePath)) {
    return new Set();
  }
  
  try {
    const data = JSON.parse(fs.readFileSync(ignorePath, 'utf8'));
    const ignored = new Set();
    
    if (Array.isArray(data)) {
      data.forEach(mod => ignored.add(mod));
    } else if (data.ignored_modules && Array.isArray(data.ignored_modules)) {
      data.ignored_modules.forEach(item => {
        if (item.module) {
          ignored.add(item.module);
        }
      });
    }
    
    return ignored;
  } catch (error) {
    console.error(`Error loading ignore list: ${error.message}`);
    return new Set();
  }
}

/**
 * Load metadata for a module
 */
function loadMetadata(metadataDir, moduleTitle) {
  const safeName = moduleTitle.replace(/:/g, '-').replace(/\//g, '-');
  const metaPath = path.join(metadataDir, `${safeName}.meta.json`);
  
  if (!fs.existsSync(metaPath)) {
    return null;
  }
  
  try {
    return JSON.parse(fs.readFileSync(metaPath, 'utf8'));
  } catch (error) {
    console.error(`Error loading metadata for ${moduleTitle}: ${error.message}`);
    return null;
  }
}

/**
 * Save metadata for a module
 */
function saveMetadata(metadataDir, moduleTitle, metadata) {
  const safeName = moduleTitle.replace(/:/g, '-').replace(/\//g, '-');
  const metaPath = path.join(metadataDir, `${safeName}.meta.json`);
  
  try {
    fs.writeFileSync(metaPath, JSON.stringify(metadata, null, 2), 'utf8');
    return true;
  } catch (error) {
    console.error(`Error saving metadata for ${moduleTitle}: ${error.message}`);
    return false;
  }
}

/**
 * Add module to ignore list
 */
function addToIgnoreList(ignorePath, moduleTitle, reason) {
  let ignoreData = { ignored_modules: [] };
  
  if (fs.existsSync(ignorePath)) {
    try {
      ignoreData = JSON.parse(fs.readFileSync(ignorePath, 'utf8'));
      if (!ignoreData.ignored_modules) {
        ignoreData.ignored_modules = [];
      }
    } catch (error) {
      console.error(`Error reading ignore list: ${error.message}`);
    }
  }
  
  // Check if already in ignore list
  const existing = ignoreData.ignored_modules.find(item => item.module === moduleTitle);
  if (existing) {
    existing.attempt_count = (existing.attempt_count || 1) + 1;
    existing.last_error = reason;
  } else {
    ignoreData.ignored_modules.push({
      module: moduleTitle,
      reason: reason,
      ignored_at: new Date().toISOString(),
      attempt_count: 1
    });
  }
  
  try {
    fs.writeFileSync(ignorePath, JSON.stringify(ignoreData, null, 2), 'utf8');
    return true;
  } catch (error) {
    console.error(`Error updating ignore list: ${error.message}`);
    return false;
  }
}

/**
  * Initialize a shared browser and page for batch operations
  */
async function initBatchBrowser() {
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  const page = await browser.newPage();
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

  return { browser, page };
}

/**
  * Clear the Scribunto console using the Clear button
  */
async function clearConsole(page) {
  const clearButton = await page.$('form button[type="button"], input[type="button"]');
  if (clearButton) {
    await clearButton.click();
  }
  await new Promise(resolve => setTimeout(resolve, 100));
}

/**
  * Execute Lua code and extract JSON output from the Scribunto console
  */
async function executeAndExtract(page, luaCode) {
  console.log(`  Executing Lua code...`);

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
    throw new Error('No JSON output found in console');
  }

  let jsonData;
  try {
    jsonData = JSON.parse(output.text);
  } catch (parseErr) {
    throw new Error(`JSON parse error: ${parseErr.message}\nOutput: ${output.text?.substring(0, 200)}`);
  }

  return jsonData;
}

/**
  * Convert a single module to JSON using Scribunto console
  * Expects an existing page from initBatchBrowser for batch mode,
  * or creates its own browser/page for single-module mode
  */
async function convertModuleToJson(moduleName, options = {}, batchPage = null) {
  const waitForOutput = options.waitForOutput ?? 1000;
  const retryDelay = options.retryDelay ?? config.retryDelayMs;

  let browser, page, ownedBrowser = false;

  if (batchPage) {
    browser = batchPage.browser;
    page = batchPage.page;
  } else {
    browser = await puppeteer.launch({
      headless: 'new',
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    page = await browser.newPage();
    await page.setUserAgent(
      'puppeteer_wf-wiki-module-mirror (https://github.com/420gaming420/wf-wiki-module-scripts)''
    );
    const editUrl = `${config.wikiBaseUrl}/w/Module:Sandbox/ScribuntoDebugConsole?action=edit`;
    console.log(`  Navigating to: ${editUrl}`);
    await page.goto(editUrl, {
      waitUntil: 'networkidle0',
      timeout: config.browserTimeout
    });
    await page.waitForSelector('#mw-scribunto-input', { timeout: 10000 });
    ownedBrowser = true;
  }

  try {
    await clearConsole(page);

    const luaCode = `local JSON = require('Module:JSON')
local data = require('${moduleName}')
mw.log(JSON.stringify(data))`;

    const jsonData = await executeAndExtract(page, luaCode);

    console.log(`  Successfully converted ${moduleName}`);
    return jsonData;

  } catch (error) {
    throw new Error(`Failed to convert ${moduleName}: ${error.message}`);
  } finally {
    if (ownedBrowser) {
      await browser.close();
    }
  }
}

/**
 * Main execution function
 */
async function main() {
  const startTime = Date.now();
  
  // Parse arguments
  const args = process.argv.slice(2);
  
  // Check for --config flag
  let configPath = 'config.ini';
  const configIndex = args.indexOf('--config');
  if (configIndex !== -1 && args[configIndex + 1]) {
    configPath = args[configIndex + 1];
    args.splice(configIndex, 2);
  }
  
  // Load configuration
  config = loadConfig(configPath);
  
  // Check for --pages flag
  let pagesFile = null;
  const pagesIndex = args.indexOf('--pages');
  if (pagesIndex !== -1 && args[pagesIndex + 1]) {
    pagesFile = args[pagesIndex + 1];
    args.splice(pagesIndex, 2);
  }
  
  // Check for --batch flag
  const batchMode = args.includes('--batch');
  
  if (batchMode && pagesFile) {
    // Batch mode with pages file
    if (!fs.existsSync(pagesFile)) {
      console.error(`Error: Pages file not found: ${pagesFile}`);
      process.exit(1);
    }
    
    let pagesData;
    try {
      pagesData = JSON.parse(fs.readFileSync(pagesFile, 'utf8'));
    } catch (error) {
      console.error(`Error parsing pages file: ${error.message}`);
      process.exit(1);
    }
    
    // Ensure pagesData is an array of objects with 'page' property
    let moduleList = [];
    if (Array.isArray(pagesData)) {
      moduleList = pagesData.map(item => {
        if (typeof item === 'string') {
          return { page: item };
        } else if (item && item.page) {
          return item;
        }
        return null;
      }).filter(Boolean);
    }
    
    if (moduleList.length === 0) {
      console.log('No modules to convert.');
      process.exit(0);
    }
    
    console.log(`\n=== WARFRAME Wiki Module Converter (Batch Mode) ===`);
    console.log(`Modules to convert: ${moduleList.length}`);
    console.log(`Output directory: ${config.outputDir}`);
    console.log(`Metadata directory: ${config.metadataDir}`);
    console.log(`Rate limit: ${config.rateLimitMs}ms between requests\n`);
    
    // Ensure output directories exist
    if (!fs.existsSync(config.outputDir)) {
      fs.mkdirSync(config.outputDir, { recursive: true });
    }
    if (!fs.existsSync(config.metadataDir)) {
      fs.mkdirSync(config.metadataDir, { recursive: true });
    }
    if (!fs.existsSync(config.logDir)) {
      fs.mkdirSync(config.logDir, { recursive: true });
    }
    
    // Load ignore list
    const ignoredModules = loadIgnoredModules(config.ignoreModulesFile);
    if (ignoredModules.size > 0) {
      console.log(`Loaded ${ignoredModules.size} ignored modules\n`);
    }
    
    // Initialize shared browser for batch
    console.log('Initializing batch browser...');
    const { browser: batchBrowser, page: batchPage } = await initBatchBrowser();

    // Process each module
    let successCount = 0;
    let failedCount = 0;
    let skippedCount = 0;

    for (let i = 0; i < moduleList.length; i++) {
      const moduleInfo = moduleList[i];
      const moduleName = moduleInfo.page;

      console.log(`\n[${i + 1}/${moduleList.length}] Converting: ${moduleName}`);

      // Check if ignored
      if (ignoredModules.has(moduleName)) {
        console.log(`  Skipped (ignored module)`);
        skippedCount++;
        continue;
      }

      // Check metadata
      const metadata = loadMetadata(config.metadataDir, moduleName);
      if (metadata && metadata.status === 'success') {
        const convertedAt = new Date(metadata.converted_at);
        const now = new Date();
        const hoursSinceConversion = (now - convertedAt) / (1000 * 60 * 60);

        if (hoursSinceConversion < config.stalenessHours) {
          console.log(`  Skipped (converted ${hoursSinceConversion.toFixed(1)} hours ago)`);
          skippedCount++;
          continue;
        }
      }

      // Try conversion (no retries — failed modules are permanently skipped)
      try {
        const jsonData = await convertModuleToJson(moduleName, {}, { browser: batchBrowser, page: batchPage });

        // Save JSON
        const safeName = moduleName.replace(/:/g, '-').replace(/\//g, '-');
        const outputPath = path.join(config.outputDir, `${safeName}.json`);
        const jsonString = JSON.stringify(jsonData, null, 2);
        fs.writeFileSync(outputPath, jsonString, 'utf8');

        // Save metadata
        const meta = {
          page: moduleName,
          converted_at: new Date().toISOString(),
          output_file: `${safeName}.json`,
          file_size: jsonString.length,
          status: 'success'
        };
        saveMetadata(config.metadataDir, moduleName, meta);

        console.log(`  Success! Saved to ${outputPath} (${(jsonString.length / 1024).toFixed(2)} KB)`);
        successCount++;

      } catch (error) {
        console.error(`  Error: ${error.message}`);
        console.error(`  Failed — added to ignore list`);

        // Add to ignore list
        addToIgnoreList(config.ignoreModulesFile, moduleName, error.message);
        failedCount++;
      }

      // Rate limiting
      if (i < moduleList.length - 1) {
        await new Promise(resolve => setTimeout(resolve, config.rateLimitMs));
      }
    }

    await batchBrowser.close();
    
    // Summary
    const endTime = Date.now();
    const totalTime = (endTime - startTime) / 1000;
    
    console.log(`\n${'='.repeat(60)}`);
    console.log('BATCH CONVERSION SUMMARY');
    console.log(`${'='.repeat(60)}`);
    console.log(`Total modules: ${moduleList.length}`);
    console.log(`Success: ${successCount}`);
    console.log(`Failed: ${failedCount}`);
    console.log(`Skipped: ${skippedCount}`);
    console.log(`Time elapsed: ${totalTime.toFixed(2)} seconds`);
    console.log(`${'='.repeat(60)}`);
    
  } else if (args.length > 0) {
    // Single module conversion
    const moduleName = args[0];
    const outputFile = args[1] || path.join(config.outputDir, `${moduleName.replace(/:/g, '-')}.json`);
    
    console.log(`\n=== WARFRAME Wiki Module Converter ===`);
    console.log(`Module: ${moduleName}`);
    console.log(`Output: ${outputFile}`);
    console.log(`Rate limit: ${config.rateLimitMs}ms between requests\n`);
    
    // Ensure output directory exists
    const outputDir = path.dirname(outputFile);
    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir, { recursive: true });
    }
    
    // Execute
    console.log('Executing...');
    
    const jsonData = await convertModuleToJson(moduleName);
    
    // Write to file
    const jsonString = JSON.stringify(jsonData, null, 2);
    fs.writeFileSync(outputFile, jsonString, 'utf8');
    
    // Save metadata
    const metadata = {
      page: moduleName,
      converted_at: new Date().toISOString(),
      output_file: path.basename(outputFile),
      file_size: jsonString.length,
      status: 'success'
    };
    saveMetadata(config.metadataDir, moduleName, metadata);
    
    const endTime = Date.now();
    const totalTime = (endTime - startTime) / 1000;
    
    console.log(`\n✅ Success!`);
    console.log(`   Saved to: ${outputFile}`);
    console.log(`   Size: ${(fs.statSync(outputFile).size / 1024).toFixed(2)} KB`);
    console.log(`   Time: ${totalTime.toFixed(2)} seconds`);
    
  } else {
    console.error('Usage: node convert_module.js <Module:Name/path> [output.json]');
    console.error('       node convert_module.js --batch --pages stale_modules.json');
    console.error('       node convert_module.js --config config.ini --batch --pages stale_modules.json');
    process.exit(1);
  }
}

/**
  * Batch conversion function (legacy support)
  */
async function convertAllModules() {
  console.log('=== Batch Conversion ===\n');

  const results = {
    success: [],
    failed: []
  };

  const { browser, page } = await initBatchBrowser();

  for (const moduleName of MODULES) {
    console.log(`\n${'='.repeat(60)}`);
    console.log(`Converting: ${moduleName}`);
    console.log('='.repeat(60));

    try {
      const jsonData = await convertModuleToJson(moduleName, {}, { browser, page });
      const outputFile = `data/json/${moduleName.replace('Module:', '').replace(/:/g, '-').replace(/\//g, '-')}.json`;

      fs.writeFileSync(outputFile, JSON.stringify(jsonData, null, 2));
      console.log(`✅ Saved: ${outputFile}`);
      results.success.push({ module: moduleName, file: outputFile });

    } catch (error) {
      console.error(`❌ Failed: ${moduleName}`);
      console.error(`   Error: ${error.message}`);
      results.failed.push({ module: moduleName, error: error.message });
    }

    // Rate limiting
    console.log(`Waiting ${config.rateLimitMs}ms before next module...`);
    await new Promise(resolve => setTimeout(resolve, config.rateLimitMs));
  }

  await browser.close();

  // Print summary report
  console.log('\n' + '='.repeat(60));
  console.log('=== BATCH CONVERSION REPORT ===');
  console.log('='.repeat(60));
  console.log(`\nTotal modules: ${MODULES.length}`);
  console.log(`Successful: ${results.success.length}`);
  console.log(`Failed: ${results.failed.length}`);

  if (results.success.length > 0) {
    console.log('\n✅ SUCCESSFUL MODULES:');
    results.success.forEach(r => {
      console.log(`   - ${r.module} -> ${r.file}`);
    });
  }

  if (results.failed.length > 0) {
    console.log('\n❌ FAILED MODULES (requires manual review):');
    results.failed.forEach(r => {
      console.log(`   - ${r.module}`);
      console.log(`     Error: ${r.error}`);
    });
  }

  console.log('\n=== BATCH COMPLETE ===');
}

// Batch modules to convert (legacy)
const MODULES = [
  'Module:ChickenTest',
  'Module:ChickenTest/data',
  'Module:Factions/data',
];

// Run if called directly
if (require.main === module) {
  if (process.argv.length > 2 && process.argv[2] === '--batch' && !process.argv.includes('--pages')) {
    convertAllModules().catch(err => {
      console.error('Fatal error:', err);
      process.exit(1);
    });
  } else {
    main().catch(err => {
      console.error('Fatal error:', err);
      process.exit(1);
    });
  }
}

// Export for testing
module.exports = { convertModuleToJson, convertAllModules, MODULES, loadConfig, loadIgnoredModules, loadMetadata, saveMetadata, addToIgnoreList, initBatchBrowser, clearConsole, executeAndExtract };
