# WARFRAME Wiki Module Scripts

> Tools for syncing, converting, and attributing WARFRAME Wiki Scribunto Lua modules to JSON.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Data Repo](https://img.shields.io/badge/Mirror-Data-blue)](https://github.com/420gaming420/wf-wiki-module-data)

## Overview

This repository contains the automated pipeline that:

1. **Detects** which WARFRAME Wiki module pages have changed since the last sync
2. **Converts** stale modules from Lua (via Puppeteer + Scribunto Debug Console) to JSON
3. **Attributes** each JSON file with source URL, license, and original Lua comments

The resulting JSON files are published to the [wf-wiki-module-data](https://github.com/420gaming420/wf-wiki-module-data) repository.

## Scripts

### `request.py` — Stale Module Detection

Queries the WARFRAME Wiki API to find modules that have been modified since the last sync.

```bash
python3 request.py [--config config.ini]
```

- Fetches page timestamps in batch via the MediaWiki API
- Compares against local `.meta.json` files
- Outputs `stale_modules.json` with modules that need updating

**Options:**
| Flag | Description |
|---|---|
| `--config CONFIG` | Path to config.ini (default: `config.ini`) |
| `--force-collect` | Force re-fetch the full module catalog from the wiki API (overwrites any cached `all_wfwiki_modules_merged.json`) |

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
5. Writes to `data/json/<ModuleName>.json` (colons and slashes in the module name are replaced with hyphens)

**Rate limiting:** 1 request per second (configurable via `config.ini`)

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
    "converter_repo": "https://github.com/420gaming420/wf-wiki-module-scripts",
    "converted_at": "2026-08-29T15:12:00.785Z"
  },
  "_comments": "-- Database for Module:Ability\n-- Note that [\"Warframe\"] subtable indexes...",
  ...existing data...
}
```

**Options:**
| Flag | Description |
|---|---|
| `--force` | Process ALL JSON files in the output directory regardless of staleness (rewrites `_attribution` and re-fetches `_comments` for every file) |
| `--dry-run` | Show what would change without writing anything |
| `--verbose` | Print detailed per-file information |

**Comment extraction:**
- Fetches live HTML from the wiki (respects `rate_limit` in config)
- Extracts the Lua code block from `<pre>` tags
- Collects all comment lines: `-- single-line`, `--[=[ multi-line ]=]`, embedded comments
- Deduplicates while preserving order

> **Note:** `--dry-run` skips all network activity. Use `--force --dry-run` to preview changes without fetching.

---

### `workflow.sh` — Full Pipeline Orchestrator

Runs the complete sync pipeline end-to-end.

```bash
bash workflow.sh [--dry-run]
```

**Steps:**
1. Run `request.py` to find stale modules
2. Run `convert_module.js --batch` to convert each stale module
3. Run `attribution.py --force` to add attribution and comments
4. Print summary with timing and counts

> **Note on `--dry-run`:** This flag only checks whether `stale_modules.json` exists and prints how many modules would be converted. It does not execute any of the pipeline steps.

**Output format:**
```
[INFO] ==================================
[INFO] WARFRAME Wiki Module Sync Workflow
[INFO] ==================================
[INFO] Request.py duration: 17s
[INFO] Convert_module.js duration: 18m 5s
[INFO] Total workflow duration: 19m 2s
[INFO] ==================================
```

## Configuration

Edit `config.ini` to customize behavior:

```ini
[wiki]
base_url = https://wiki.warframe.com
api_url = https://wiki.warframe.com/api.php
user_agent = User-Agent: clientname/version (contact information e.g. username, email) framework/version...
rate_limit = 1.0          # seconds between requests
staleness_hours = 24      # only convert modules newer than this

[conversion]
timeout_ms = 60000        # per-module Puppeteer timeout
browser_timeout = 30000   # browser launch timeout

[paths]
stale_modules = stale_modules.json
ignore_modules = ignore_modules.json
output_dir = data/json
metadata_dir = data/json

[github]
max_consecutive_errors = 3  # disable action after N crashes
url = https://github.com/420gaming420/wf-wiki-module-scripts
```

## Ignored Modules

**337 modules** cannot be converted automatically. They are listed in `ignore_modules.json` and skipped during conversion. Common reasons:

| Category | Reason |
|---|---|
| Unjsonifiable types | Functions/callables in Lua tables (e.g. `Module:JSON` fails at line 147) |
| Missing doc pages | `/doc` subpages that don't exist as wiki modules |
| mw.loadData errors | Tables with metatables (MediaWiki-specific) |
| JSON parse errors | `Infinity` values in Lua output (not valid JSON) |

## Data Repository

Converted JSON files are published to:
**<https://github.com/420gaming420/wf-wiki-module-data>**

This is a **read-only mirror** — to modify data, edit the source on the [WARFRAME Wiki](https://wiki.warframe.com).

## Requirements

- **Node.js** 22+ (for `convert_module.js`)
- **Python** 3.10+ (for `request.py`, `attribution.py`)
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

