# WARFRAME Wiki Module Scripts

> Tools for syncing, converting, and attributing WARFRAME Wiki Scribunto Lua modules to JSON.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Data Repo](https://img.shields.io/badge/Mirror-Data-blue)](https://github.com/420gaming420/wf-wiki-module-data)

## Overview

This repository contains the automated pipeline that:

1. **Detects** which WARFRAME Wiki module pages have changed since the last sync
2. **Archives** all modules as HTML and extracted Lua source code
3. **Converts** all pages from HTML to Markdown (preserving documentation, tables, and code)
4. **Converts** stale modules from Lua (via Puppeteer + Scribunto Debug Console) to JSON
5. **Attributes** each JSON file with source URL, license, and original Lua comments

The resulting JSON files are published to the [wf-wiki-module-data](https://github.com/420gaming420/wf-wiki-module-data) repository.

## Scripts

### `request.py` — Stale Module Detection

Queries the WARFRAME Wiki API to find modules that have been modified since the last sync.

```bash
python3 request.py [--config config.ini]
```

- Fetches the full module catalog from the wiki API on every run
- Fetches page timestamps in batch via the MediaWiki API
- Compares against local `.meta.json` files
- Outputs `stale_modules.json` with modules that need updating

**Options:**
| Flag | Description |
|---|---|
| `--config CONFIG` | Path to config.ini (default: `config.ini`) |

---

### `download.py` — HTML Archive Downloader

Downloads HTML pages for all wiki modules (excluding sandbox) to `data/html/`.

```bash
python3 download.py [--config config.ini] [--force] [--page NAME]
```

- Downloads ~515 actual modules (filters out sandbox)
- Respects `staleness_hours` to avoid redundant downloads
- Skips modules with matching wiki timestamps
- **Does NOT** use `ignore_modules.json` (archives everything)

**Options:**
| Flag | Description |
|---|---|
| `--config CONFIG` | Path to config.ini (default: `config.ini`) |
| `--force` | Force re-download all modules regardless of staleness |
| `--page NAME` | Download only a single module (for testing) |

**Example:**
```bash
python3 download.py --page "Module:Arcane/infobox"
```

---

### `extract_lua.py` — Lua Source Extractor

Extracts all Lua code blocks from downloaded HTML files to `data/lua/`.

```bash
python3 extract_lua.py [--config config.ini] [--force]
```

- Reads HTML files from `data/html/`
- Extracts **all** `<pre>` blocks (including examples, schemas, and documentation code)
- Saves each block as a separate file: `<ModuleName>_N.lua` (e.g. `Module-Ability-data_0.lua`, `_1.lua`)
- Saves metadata to `<ModuleName>.meta.json` with `lua_files` listing all block filenames and `lua_block_count`
- Respects `staleness_hours` to avoid redundant extraction

**Options:**
| Flag | Description |
|---|---|
| `--config CONFIG` | Path to config.ini (default: `config.ini`) |
| `--force` | Force re-extraction of all modules |

---

### `extract_text.py` — HTML to Markdown Converter

Converts all wiki HTML pages to Markdown format, preserving full page content including headings, paragraphs, lists, tables, links, and Lua code blocks with syntax highlighting.

```bash
python3 extract_text.py [--config config.ini] [--force]
```

- Reads HTML files from `data/html/`
- Converts the `mw-parser-output` div to Markdown using `markdownify`
- Strips MediaWiki line-number spans from `<pre>` blocks before conversion
- Wraps all code blocks with ` ```lua ` syntax highlighting
- Includes YAML frontmatter with `title`, `wiki_url`, and `wiki_timestamp`
- Preserves TOC sections for module cross-reference links
- Saves to `data/markdown/<ModuleName>.md` with `.meta.json` metadata
- Respects `staleness_hours` to avoid redundant extraction

**Options:**
| Flag | Description |
|---|---|
| `--config CONFIG` | Path to config.ini (default: `config.ini`) |
| `--force` | Force re-extraction of all modules |

---

### `convert_module.js` — Lua to JSON Conversion

Uses Puppeteer to open a Scribunto Debug Console on the wiki page in a headless browser, execute each module and extract the resulting JSON.

```bash
# Convert a single module
node convert_module.js "Module:Ability/data"

# Convert all stale modules from batch
node convert_module.js --batch --pages stale_modules.json

# With custom config
node convert_module.js --config config.ini --batch --pages stale_modules.json
```

**How it works:**
1. Launches a single headless Chromium browser
2. Navigates to `https://wiki.warframe.com/w/Module:Sandbox/ScribuntoDebugConsole?action=edit`
3. Executes Lua code that requires the module, stringifies it with `Module:JSON`, and logs the result via `mw.log()`
4. Extracts the JSON output from the `.mw-scribunto-print` div
5. Sanitizes invalid JSON tokens (`inf`, `-inf`, `NaN`) produced by Scribunto's `Module:JSON` by replacing them with `null`
6. Writes to `data/json/<ModuleName>.json` (colons and slashes in the module name are replaced with hyphens)

**Rate limiting:** 1 request per second (configurable via `config.ini`)

> **Note:** Some modules produce `inf` values (e.g. `FireRate:inf` from division by zero, `AmmoMax:inf` for infinite ammo weapons). These are serialized by `Module:JSON` as bare tokens that are invalid JSON. The converter sanitizes them to `null` before parsing.

---

### `scribunto_daemon.js` — Persistent Scribunto Console

Launches a headless Chromium browser connected to the WARFRAME Wiki Scribunto Debug Console and exposes an HTTP API for executing Lua code.

```bash
# Start the daemon (runs until killed or 60 minutes idle)
node scribunto_daemon.js [--config config.ini]
```

The daemon stays alive and accepts multiple requests. It writes its port to `/tmp/scribunto_daemon.pid` for discovery.

---

### `scribunto_console.js` — CLI Client

Sends Lua code to a running daemon and prints the output.

```bash
# Execute from stdin pipe
cat script.lua | node scribunto_console.js

# Execute from file
node scribunto_console.js --script hello.lua

# Pretty-print JSON output
cat script.lua | node scribunto_console.js --json

# With custom config
node scribunto_console.js --config config.ini --script hello.lua
```

**Features:**
- Reads Lua from `--script` file or stdin
- Automatically discovers daemon port via PID file
- `--json` flag pretty-prints if output is valid JSON
- Exit code 1 on errors (Lua errors, connection failed, etc.)

---

### `attribution.py` — Attribution & Comments

Adds source attribution and Lua comments to each converted JSON file.

```bash
python3 attribution.py [--config config.ini] [--force] [--dry-run] [--verbose]
```

**What it adds to each JSON file:**

```json
{
  "_attribution": {
    "source_url": "https://wiki.warframe.com/w/Module:Ability/data",
    "license": "CC BY-NC-SA 3.0",
    "license_url": "https://creativecommons.org/licenses/by-nc-sa/3.0/",
    "converter_repo": "https://github.com/your-username/wf-wiki-module-scripts",
    "converted_at": "2026-08-29T15:12:00.785Z"
  },
  "_comments": "-- Database for Module:Ability\n-- Note that [\"Warframe\"] subtable indexes...",
  ...existing data...
}
```

**Options:**
| Flag | Description |
|---|---|
| `--force` | Process ALL JSON files in the output directory regardless of staleness (rewrites `_attribution`) |
| `--dry-run` | Show what would change without writing anything |
| `--verbose` | Print detailed per-file information |

**Comment extraction:**
- Reads Lua source from local `data/lua/` files (no network requests)
- Extracts all comment lines: `-- single-line`, `--[=[ multi-line ]=]`, embedded comments
- Deduplicates while preserving order

> **Note:** `--dry-run` skips all file writes. Use `--force --dry-run` to preview changes.

---

### `workflow.sh` — Full Pipeline Orchestrator

Runs the complete sync pipeline end-to-end.

```bash
bash workflow.sh [--dry-run]
```

**Steps:**
1. Run `request.py` to find stale modules
2. Run `download.py` to archive HTML files
3. Run `extract_lua.py` to extract Lua source
4. Run `extract_text.py` to convert HTML to Markdown
5. Run `convert_module.js --batch` to convert stale modules to JSON
6. Run `attribution.py` to add attribution and comments
7. Print summary with timing and counts

> **Note on `--dry-run`:** This flag only checks whether `stale_modules.json` exists and prints how many modules would be converted. It does not execute any of the pipeline steps.

**Error handling:**
- `request.py` failure: aborts workflow
- `convert_module.js` failure: aborts workflow
- `download.py` / `extract_lua.py` / `extract_text.py` / `attribution.py` failure: logs warning and continues

**Output format:**
```
[INFO] ==================================
[INFO] WARFRAME Wiki Module Sync Workflow
[INFO] ==================================
[INFO] request.py duration: 17s
[INFO] download.py duration: 5m 30s
[INFO] extract_lua.py duration: 2m 15s
[INFO] extract_text.py duration: 1m 0s
[INFO] convert_module.js duration: 18m 5s
[INFO] Total workflow duration: 27m 7s
[INFO] ==================================
```

## Data Structure

```
data/
├── html/           # ~616 HTML files (one per wiki module)
│   ├── Module-Ability-data.html
│   ├── Module-Ability-data.meta.json
│   └── ...
├── lua/            # ~952 Lua source files (extracted from HTML)
│   ├── Module-Ability-data_0.lua
│   ├── Module-Ability-data.meta.json
│   └── ...
├── markdown/       # ~616 Markdown files (full page documentation)
│   ├── Module-Ability-data.md
│   ├── Module-Ability-data.meta.json
│   └── ...
├── json/           # ~177 JSON files (Scribunto-converted)
│   ├── Module-Ability-data.json
│   ├── Module-Ability-data.meta.json
│   └── ...
└── logs/           # Workflow logs
```

**Metadata format:**
```json
{
  "page": "Module:Ability/data",
  "wiki_timestamp": "2026-07-29T23:49:20Z",
  "downloaded_at": "2026-08-30T16:00:00Z",
  "extracted_at": "2026-08-30T16:00:01Z",
  "converted_at": "2026-08-30T16:00:02Z",
  "file_size": 221044,
  "status": "success"
}
```

## API Cache System

To minimize API requests and respect wiki rate limits, only `request.py` makes API calls.
All other scripts use cached data generated by `request.py`:

| Cache File | Generated By | Used By | Purpose |
|---|---|---|---|
| `all_wfwiki_modules_merged.json` | `request.py` | `download.py` | Module catalog (titles, namespaces) |
| `all_timestamps.json` | `request.py` | `download.py` | Current wiki timestamps for all modules |
| `stale_modules.json` | `request.py` | `convert_module.js` | Modules needing JSON conversion |

**API Request Count:**
- `request.py`: ~13 requests (catalog + batched timestamps)
- `download.py`: **0 requests** (uses cache)
- `extract_lua.py`: **0 requests** (reads local files)
- `extract_text.py`: **0 requests** (reads local files)
- `attribution.py`: **0 requests** (reads local files)
- **Total: ~13 requests per full sync**

All cache files are git-ignored and regenerated on each `request.py` run.

## Configuration

```ini
[wiki]
base_url = https://wiki.warframe.com
api_url = https://wiki.warframe.com/api.php
rate_limit = 1.0          # seconds between requests
staleness_hours = 24      # only process modules newer than this

[user_agents]
# Replace with your own contact information
wiki_client = WFModuleMirror/1.0 (your-contact@example.com)
download = WFModuleDownload/1.0 (your-contact@example.com)
attribution = WFModuleAttribution/1.0 (your-contact@example.com)

[conversion]
timeout_ms = 60000        # per-module Puppeteer timeout
browser_timeout = 30000   # browser launch timeout

[paths]
stale_modules = stale_modules.json
ignore_modules = ignore_modules.json
catalog_file = all_wfwiki_modules_merged.json
timestamps_file = all_timestamps.json
output_dir = data/json
metadata_dir = data/json
html_dir = data/html
lua_dir = data/lua
markdown_dir = data/markdown
log_dir = data/logs

[github]
max_consecutive_errors = 3  # disable action after N crashes
url = https://github.com/your-username/wf-wiki-module-scripts
```

> **Note:** `config.ini` is git-ignored. A template is generated on first run.

## Ignored Modules

**337 modules** cannot be converted automatically. They are listed in `ignore_modules.json` and skipped during JSON conversion. Common reasons:

| Category | Reason |
|---|---|
| Unjsonifiable types | Functions/callables in Lua tables (e.g. `Module:JSON` fails at line 147) |
| Missing doc pages | `/doc` subpages that don't exist as wiki modules |
| mw.loadData errors | Tables with metatables (MediaWiki-specific) |
| JSON parse errors | `Infinity` values in Lua output (not valid JSON) |

> **Note:** `ignore_modules.json` only affects JSON conversion. HTML/Lua archives download all modules regardless.

## Utility Modules

Shared code is extracted to `utils/` to avoid duplication:

- `utils/wiki_client.py` — Rate-limited HTTP client (1s minimum delay, gzip support)
- `utils/lua_extractor.py` — HTML parsing and Lua comment extraction

## Requirements

- **Node.js** 22+ (for `convert_module.js`)
- **Python** 3.10+ (for `request.py`, `download.py`, `extract_lua.py`, `extract_text.py`, `attribution.py`)
- **beautifulsoup4** >= 4.12.0 (for `extract_text.py`)
- **markdownify** >= 0.13.0 (for `extract_text.py`)
- **puppeteer** npm package
- **bash** (for `workflow.sh`)

## License

| Component | License |
|---|---|
| **Scripts** (Python, JS, bash) | [MIT](https://opensource.org/licenses/MIT) |
| **Data** (JSON output) | [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/) — same as the WARFRAME Wiki |

This github repo is not affiliated with Digital Extremes or Warframe or the WARFRAME Wiki.

```
Warframe, the Warframe logo, and Evolution Engine are registered trademarks of Digital Extremes Ltd.

All user-contributed code on articles in the Module and MediaWiki namespaces are licensed under Creative Commons Attribution–Share Alike License (CC BY-SA) unless otherwise specified. See https://weirdgloop.org/terms/ for full legal details.
https://creativecommons.org/licenses/by-nc/3.0/ - CC BY-SA summary
https://creativecommons.org/licenses/by-nc/3.0/legalcode - full CC BY-SA legal code

Some third-party forks use different licenses that are compatible with CC BY-SA. See the respective Module page's documentation for more details.

All trademarks are the property of their respective owners.
```

See [https://wiki.warframe.com/w/WARFRAME_Wiki:Licensing](https://wiki.warframe.com/w/WARFRAME_Wiki:Licensing) for details.

See [ATTRIBUTION.md](https://github.com/420gaming420/wf-wiki-module-data/blob/main/ATTRIBUTION.md) in the [data repository](https://github.com/420gaming420/wf-wiki-module-data) for attribution requirements on the data.

