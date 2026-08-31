# Scribunto Console Usage Guide

A comprehensive guide to testing WARFRAME Wiki Lua modules locally using the Scribunto Debug Console.

## Table of Contents

1. [Overview](#overview)
2. [Starting the Daemon](#starting-the-daemon)
3. [Basic Usage](#basic-usage)
4. [Understanding Scribunto's Environment](#understanding-scribunto-environment)
5. [Module Loading Patterns](#module-loading-patterns)
6. [Workarounds and Fixes](#workarounds-and-fixes)
7. [Troubleshooting](#troubleshooting)
8. [Advanced Testing](#advanced-testing)

---

## Overview

The Scribunto Debug Console is a web-based Lua interpreter hosted on the WARFRAME Wiki. This guide explains how to use it locally to test, develop, and debug Wiki modules without modifying the actual wiki pages.

### What is Scribunto?

Scribunto is a MediaWiki extension that allows Lua code to be executed on wiki pages. The WARFRAME Wiki uses it extensively for:
- Data storage (ability stats, weapon mods, etc.)
- UI generation (infoboxes, tooltips)
- Utility libraries (JSON parsing, string manipulation)

### The Console

The Scribunto Debug Console is available at:
```
https://wiki.warframe.com/w/Module:Sandbox/ScribuntoDebugConsole?action=edit
```

It provides a text input field where you can paste Lua code and see the output.

---

## Starting the Daemon

The daemon is a persistent Node.js process that maintains a headless Chromium browser connected to the Scribunto console.

### Start the daemon:

```bash
nohup node scribunto_daemon.js > /tmp/daemon.log 2>&1 &
```

### Verify it's running:

```bash
curl http://localhost:$(cat /tmp/scribunto_daemon.pid | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['port'])")/status
```

Expected output:
```json
{"ready":true,"idle_seconds":0}
```

### Stop the daemon:

```bash
kill $(cat /tmp/scribunto_daemon.pid | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['pid'])")
```

---

## Basic Usage

### Using --script flag:

```bash
node scribunto_console.js --script data/lua/Module-JSON_1.lua
```

### Using stdin:

```bash
cat script.lua | node scribunto_console.js
```

### Pretty-print JSON output:

```bash
echo 'mw.log(JSON.stringify({test=1}))' | node scribunto_console.js --json
```

---

## Understanding Scribunto's Environment

### Key Differences from Standard Lua

| Feature | Standard Lua | Scribunto |
|---------|-------------|-----------|
| `require()` | Loads files from filesystem | Loads wiki modules by name |
| `mw.loadData()` | Doesn't exist | Loads data tables from wiki |
| `print()` | Prints to stdout | Works in console |
| `mw.log()` | Doesn't exist | Primary output method |
| `return` | Valid at top-level | **Invalid** (wrapped in function) |

### The Console Wraps Input in a Function

When you paste code into the Scribunto console, it's executed as if wrapped in:
```lua
function()
  -- your code here
end
```

This means:
- `return` statements at the top level are **syntax errors**
- Variables defined in the console are local to that execution
- Each execution is independent

### The `mw` Global Table

Scribunto provides a global `mw` table with several methods:

```lua
-- Load data from another module
local data = mw.loadData([[Module:Ability/data]])

-- Log output to console
mw.log("Hello", "World")
mw.log(1 + 1)

-- Access the current frame (for invoked modules)
local frame = mw.getCurrentFrame()
```

---

## Module Loading Patterns

### Pattern 1: Standard Module (with `return`)

Most modules end with `return p` or `return json`. The `scribunto_console.js` script automatically strips trailing `return` statements.

Example (`Module-JSON_1.lua`):
```lua
local json = {}

function json.stringify(obj)
  -- ... implementation ...
end

return json  -- This is stripped automatically
```

After stripping, the module loads successfully:
```bash
node scribunto_console.js --script data/lua/Module-JSON_1.lua
```

### Pattern 2: Data Modules (with `mw.loadData`)

Data modules use `mw.loadData()` to load other data modules:
```lua
local AbilityData = mw.loadData([[Module:Ability/data]])
local ConclaveData = mw.loadData([[Module:Ability/Conclave/data]])
```

These work in the console because the wiki environment provides the data.

### Pattern 3: Modules with Dependencies

Some modules `require()` other modules:
```lua
local JSON = require('Module:JSON')
local Table = require('Module:Table')
```

These work in the console because the wiki has all modules loaded.

---

## Workarounds and Fixes

### Fix 1: Strip Trailing `return` Statements

The `scribunto_console.js` script automatically strips trailing `return` statements:

```javascript
// In scribunto_console.js
let lines = luaCode.split('\n');
while (lines.length > 0 && lines[lines.length - 1].trim() === '') lines.pop();
while (lines.length > 0 && lines[lines.length - 1].trim().match(/^return\b/)) lines.pop();
luaCode = lines.join('\n');
```

### Fix 2: Strip `<nowiki>` Tags

The `utils/lua_extractor.py` script strips MediaWiki `<nowiki>` tags:

```python
# In utils/lua_extractor.py
clean = re.sub(r"<nowiki[^>]*>", "", clean, flags=re.IGNORECASE)
clean = re.sub(r"</nowiki>", "", clean, flags=re.IGNORECASE)
```

This prevents syntax errors from MediaWiki artifacts in extracted Lua files.

### Manual Testing with `mw.log()`

If a module doesn't produce output, add `mw.log()` calls:

```lua
-- Load the module (paste the code)
local json = {}
function json.stringify(obj) return tostring(obj) end

-- Test it
mw.log(json.stringify({test=1}))
```

---

## Troubleshooting

### Error: `Waiting for selector '.mw-scribunto-print' failed`

**Cause:** The module executed but produced no output (no `mw.log()` calls).

**Solution:** Add `mw.log()` calls to your test code, or check if the module loaded successfully by testing a simple expression:
```lua
mw.log(type(json))  -- Should print "table"
```

### Error: `'end' expected (to close 'function' at line 1) near 'return'`

**Cause:** The extracted Lua file has a `return` statement at the end.

**Solution:** The `scribunto_console.js` fix should handle this. If not, manually remove the `return` line from the file.

### Error: `This console session is too large`

**Cause:** The module is too large for the console to handle.

**Solution:** 
- Test smaller modules first
- Use `extract_lua.py` to extract individual blocks
- Consider testing in smaller chunks

### Error: `attempt to index global 'X' (a nil value)`

**Cause:** The module references a global that wasn't defined.

**Solution:** 
- Check if the module requires another module
- Mock the missing global in your test code:
```lua
-- Mock missing module
JSON = { stringify = function(t) return tostring(t) end }
```

### No Output Found

**Cause:** The module loaded successfully but didn't call `mw.log()`.

**Solution:** This is normal for library modules. Test by calling a function:
```lua
mw.log(JSON.stringify({test=1}))
```

---

## Advanced Testing

### Creating Test Scripts

Create a test script in `data/custom/`:

```lua
-- data/custom/test-my-module.lua

-- Mock environment if needed
mw = mw or {
  loadData = function(name) return {} end,
  log = print
}

-- Load the module
local code = [[
local p = {}
function p.test() return 42 end
return p
]]
local module = load(code)()

-- Test the module
mw.log("Module loaded:", type(module))
mw.log("Test result:", module.test())
```

Run it:
```bash
node scribunto_console.js --script data/custom/test-my-module.lua
```

### Using the Daemon Directly

For more control, use the daemon's HTTP API:

```bash
curl -X POST http://localhost:33795/execute \
  -H 'Content-Type: application/json' \
  -d '{"code": "mw.log(1+1)"}'
```

---

## Best Practices

1. **Always add `mw.log()` calls** when testing modules
2. **Strip `return` statements** before pasting into console
3. **Test modules in isolation** before testing with dependencies
4. **Use `pcall()` for error handling**:
   ```lua
   local success, result = pcall(module.function, args)
   if not success then
     mw.log("Error:", result)
   end
   ```
5. **Clear the console** between tests to avoid state leakage

---

## Related Files

- `scribunto_daemon.js` - Persistent browser daemon
- `scribunto_console.js` - CLI client for the daemon
- `utils/lua_extractor.py` - Extracts Lua from wiki HTML
- `data/lua/` - Extracted Lua modules
- `data/markdown/` - Markdown documentation for modules
