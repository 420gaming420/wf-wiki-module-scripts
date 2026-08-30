#!/usr/bin/env python3
"""
Attribution.py — Add attribution metadata to WARFRAME Wiki module JSON files.

Adds _attribution and _comments keys to the top level of each JSON file in
data/json/.

Attribution data is sourced from config.ini and the corresponding .meta.json file (for converted_at timestamp).

Comments are extracted from the Lua source code in the live wiki HTML pages and stored in _comments.

Usage:
    python attribution.py [--config CONFIG] [--dry-run] [--verbose] [--force]
"""

import argparse
import configparser
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path


# License constants (hardcoded, not configurable)
LICENSE = "CC BY-NC-SA 3.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/3.0/"


def load_config(config_path: Path) -> configparser.ConfigParser:
    """
    Load configuration from INI file.

    Args:
        config_path: Path to config file

    Returns:
        Parsed ConfigParser instance

    Raises:
        SystemExit: If config file is missing required sections
    """
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    config = configparser.ConfigParser()
    config.read(config_path)

    required_sections = ["wiki", "paths"]
    for section in required_sections:
        if not config.has_section(section):
            print(
                f"Error: Missing required section [{section}] in {config_path}",
                file=sys.stderr,
            )
            sys.exit(1)

    return config


def get_base_url(config: configparser.ConfigParser) -> str:
    """Extract the wiki base URL from config."""
    return config.get("wiki", "base_url").rstrip("/")


def get_converter_repo(config: configparser.ConfigParser) -> str:
    """Extract the converter repo URL from config."""
    if not config.has_section("github") or not config.has_option("github", "url"):
        return "https://github.com/placeholder/placeholder"
    return config.get("github", "url").strip()


def get_rate_limit(config: configparser.ConfigParser) -> float:
    """Extract the rate limit in seconds from config."""
    if config.has_section("wiki") and config.has_option("wiki", "rate_limit"):
        try:
            return float(config.get("wiki", "rate_limit"))
        except ValueError:
            pass
    return 1.0


# Tracks time of last fetch to enforce rate limiting
_last_fetch_time: float = 0.0


def rate_limited_fetch(url: str, rate_limit: float) -> str | None:
    """
    Fetch an HTML page with rate limiting to avoid IP bans.

    Args:
        url: Full URL to the wiki page
        rate_limit: Minimum seconds between requests

    Returns:
        HTML content string, or None if fetch failed
    """
    global _last_fetch_time
    elapsed = time.time() - _last_fetch_time
    if elapsed < rate_limit:
        time.sleep(rate_limit - elapsed)
    _last_fetch_time = time.time()
    return fetch_html(url)


def fetch_html(url: str) -> str | None:
    """
    Fetch an HTML page from the wiki and return its content.

    Args:
        url: Full URL to the wiki page

    Returns:
        HTML content string, or None if fetch failed
    """
    try:
        import urllib.request
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "clientname/version (contact information e.g. username, email) framework/version..."
            }
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except (OSError, ValueError) as e:
        print(f"  Warning: Failed to fetch {url}: {e}", file=sys.stderr)
        return None


def load_meta_for_file(json_path: Path) -> tuple[dict | None, str]:
    """
    Load metadata for a JSON file using its corresponding .meta.json.

    Args:
        json_path: Path to the JSON file

    Returns:
        Tuple of (metadata dict or None, module_name string)
    """
    meta_path = json_path.with_suffix(".meta.json")
    if not meta_path.exists():
        return None, ""

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        module_name = meta.get("page", "")
        return meta, module_name
    except (json.JSONDecodeError, OSError) as e:
        print(f"  Warning: Failed to read meta for {json_path.name}: {e}", file=sys.stderr)
        return None, ""


def build_attribution(
    module_name: str,
    base_url: str,
    converter_repo: str,
    converted_at: str,
) -> dict:
    """
    Build the _attribution dict for a module.

    Args:
        module_name: Wiki module name
        base_url: Wiki base URL
        converter_repo: GitHub repo URL
        converted_at: ISO timestamp from meta

    Returns:
        Attribution dict
    """
    source_url = f"{base_url}/w/{urllib.parse.quote(module_name, safe=':/')}"
    return {
        "source_url": source_url,
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "converter_repo": converter_repo,
        "converted_at": converted_at,
    }


# ---------------------------------------------------------------------------
# Lua comment extraction (from offline HTML cache)
# ---------------------------------------------------------------------------

def extract_lua_from_html(html: str) -> str | None:
    """
    Extract the main Lua code block from a wiki HTML page.

    Picks the largest <pre> block that contains 'local ' or 'return '.

    Args:
        html: Raw HTML string

    Returns:
        Cleaned Lua source code, or None if no code found
    """
    pre_blocks = re.findall(r"<pre[^>]*>(.*?)</pre>", html, re.DOTALL)
    best = None
    for block in pre_blocks:
        clean = re.sub(r"<[^>]+>", "", block)
        clean = clean.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        clean = clean.replace("&quot;", '"').replace("&#39;", "'")
        if "local " in clean or "return " in clean:
            if best is None or len(clean) > len(best):
                best = clean
    return best


def extract_comments(lua_code: str) -> str:
    """
    Extract all comment lines from Lua source code.

    Handles:
    - Single-line comments: -- text
    - Multi-line comments: --[=[ ... ]=] and --[[ ... ]]
    - Comment lines embedded anywhere in the code (not just leading block)

    Args:
        lua_code: Cleaned Lua source string

    Returns:
        Formatted comment string, or empty string if no comments found
    """
    if not lua_code:
        return ""

    lines = lua_code.split("\n")
    comment_lines: list[str] = []
    in_multiline = False
    multiline_buffer: list[str] = []

    for line in lines:
        stripped = line.lstrip()

        if in_multiline:
            multiline_buffer.append(line)
            # Check for multi-line comment end: ]=] or ]]
            if re.search(r"\]=\]\s*$", stripped) or re.search(r"\]\]\s*$", stripped):
                in_multiline = False
                comment_lines.extend(multiline_buffer)
                multiline_buffer = []
            continue

        if stripped.startswith("--"):
            # Check for multi-line comment start: --[=[ or --[[
            if re.search(r"--\[[=]*\s*$", stripped) or re.search(r"--\[\[", stripped):
                in_multiline = True
                multiline_buffer = [line]
                # Check if it ends on the same line
                if re.search(r"\]=\]\s*$", stripped) or re.search(r"\]\]\s*$", stripped):
                    comment_lines.extend(multiline_buffer)
                    multiline_buffer = []
                    in_multiline = False
            else:
                comment_lines.append(line)

    if not comment_lines:
        return ""

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for line in comment_lines:
        key = line.strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(line)

    return "\n".join(unique)





# ---------------------------------------------------------------------------
# Stale module loading
# ---------------------------------------------------------------------------

def load_stale_modules(stale_file: Path) -> set[str] | None:
    """
    Load stale module names from stale_modules.json.

    Args:
        stale_file: Path to stale_modules.json

    Returns:
        Set of module name strings, or None if file not found
    """
    if not stale_file.exists():
        return None
    try:
        with open(stale_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Support both list of strings and list of dicts
        names: set[str] = set()
        for item in data:
            if isinstance(item, str):
                names.add(item)
            elif isinstance(item, dict):
                names.add(item.get("page", item.get("module", "")))
        return names
    except (json.JSONDecodeError, OSError) as e:
        print(f"  Warning: Failed to read stale modules: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# File processing
# ---------------------------------------------------------------------------

def process_file(
    json_path: Path,
    base_url: str,
    converter_repo: str,
    stale_modules: set[str] | None,
    rate_limit: float,
    force: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
) -> tuple[bool, str]:
    """
    Process a single JSON file: add or update attribution and comments.

    Args:
        json_path: Path to the JSON file
        base_url: Wiki base URL
        converter_repo: GitHub repo URL
        stale_modules: Set of stale module names, or None (skip staleness check)
        rate_limit: Minimum seconds between HTTP requests
        force: If True, skip staleness check
        dry_run: If True, only show what would change
        verbose: If True, print detailed info

    Returns:
        Tuple of (success, message)
    """
    # Load metadata
    meta, module_name = load_meta_for_file(json_path)
    if meta is None:
        return False, f"No metadata found for {json_path.name}"

    if not module_name:
        return False, f"No 'page' field in metadata for {json_path.name}"

    converted_at = meta.get("converted_at", datetime.now(timezone.utc).isoformat())

    # Check staleness (skip if --force)
    if not force and stale_modules is not None:
        if module_name not in stale_modules:
            if verbose:
                return True, f"Skipped (not stale, --force not set): {json_path.name}"
            return True, f"Skipped (not stale): {json_path.name}"

    # Load JSON
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return False, f"Failed to read {json_path.name}: {e}"

    # Non-dict JSON: wrap content in a dict
    if not isinstance(data, dict):
        data = {"_comments": "", "_attribution": {}, "data": data}
        wrap_type = type(data["data"]).__name__
    else:
        wrap_type = None

    # Build new attribution
    new_attribution = build_attribution(module_name, base_url, converter_repo, converted_at)

    # Fetch HTML and extract comments (skip fetch in dry-run mode)
    source_url = new_attribution["source_url"]
    comment_text = ""
    if not dry_run:
        html_content = rate_limited_fetch(source_url, rate_limit)
        if html_content:
            lua_code = extract_lua_from_html(html_content)
            if lua_code:
                comment_text = extract_comments(lua_code)
        elif verbose:
            print(f"  Warning: Could not fetch {source_url}", file=sys.stderr)

    # Always update _attribution and _comments — never skip
    if "_attribution" in data:
        old_attribution = data["_attribution"]
        attribution_changed = old_attribution != new_attribution
        comments_changed = data.get("_comments", "") != comment_text

        if attribution_changed or comments_changed:
            if verbose:
                changes = []
                if attribution_changed:
                    for key in new_attribution:
                        if old_attribution.get(key) != new_attribution.get(key):
                            changes.append(f"  {key}: {old_attribution.get(key, '<missing>')} -> {new_attribution[key]}")
                if comments_changed:
                    old_len = len(data.get("_comments", ""))
                    new_len = len(comment_text)
                    changes.append(f"  comments: {old_len} -> {new_len} chars")
                msg = f"Updating {json_path.name}:\n" + "\n".join(changes)
            else:
                msg = f"Updated: {json_path.name}"
        else:
            if verbose:
                return True, f"Already up-to-date: {json_path.name}"
            return True, f"Skipped (unchanged): {json_path.name}"
    else:
        msg = f"Added attribution: {json_path.name}"

    if verbose:
        msg_lines = [
            f"{msg}:",
            f"  source_url: {new_attribution['source_url']}",
            f"  license: {new_attribution['license']}",
            f"  converter_repo: {new_attribution['converter_repo']}",
            f"  converted_at: {new_attribution['converted_at']}",
        ]
        if comment_text:
            msg_lines.append(f"  comments: {len(comment_text.splitlines())} lines ({len(comment_text)} chars)")
        msg = "\n".join(msg_lines)

    if dry_run:
        if verbose:
            msg += "\n  (dry run — no changes written)"
        return True, msg

    if wrap_type:
        data["_attribution"] = new_attribution
        data["_comments"] = comment_text
    else:
        # Preserve existing top-level order: keep _attribution and _comments at top
        existing_keys = list(data.keys())
        ordered = {"_attribution": new_attribution, "_comments": comment_text}
        for key in existing_keys:
            if key not in ("_attribution", "_comments"):
                ordered[key] = data[key]
        data = ordered

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return True, msg


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add attribution metadata to WARFRAME Wiki module JSON files"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.ini"),
        help="Path to config.ini (default: config.ini)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed per-file information",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Process all files regardless of staleness",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    base_url = get_base_url(config)
    converter_repo = get_converter_repo(config)
    rate_limit = get_rate_limit(config)
    output_dir = Path(config.get("paths", "output_dir"))

    if not output_dir.exists():
        print(f"Error: Output directory not found: {output_dir}", file=sys.stderr)
        return 1

    # Load stale modules list (if available)
    stale_file = Path(config.get("paths", "stale_modules", fallback="stale_modules.json"))
    stale_modules = load_stale_modules(stale_file)
    if stale_modules is not None:
        print(f"Loaded {len(stale_modules)} stale modules from {stale_file.name}")
    else:
        print(f"No stale_modules.json found (processing all files)")

    # Collect all .json files (skip .meta.json)
    json_files = sorted(output_dir.glob("*.json"))
    json_files = [f for f in json_files if not f.name.endswith(".meta.json")]

    if not json_files:
        print("No JSON files found in output directory.")
        return 0

    print(f"Found {len(json_files)} JSON file(s) in {output_dir}")
    print(f"Rate limit: {rate_limit}s between requests")
    if args.dry_run:
        print("(dry run mode — no changes will be written)\n")
    print()

    success_count = 0
    skip_count = 0
    error_count = 0
    errors = []

    for json_path in json_files:
        ok, msg = process_file(
            json_path,
            base_url,
            converter_repo,
            stale_modules,
            rate_limit,
            args.force,
            args.dry_run,
            args.verbose,
        )
        if ok:
            success_count += 1
            print(msg)
        else:
            error_count += 1
            errors.append((json_path.name, msg))

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total files scanned: {len(json_files)}")
    print(f"Processed successfully: {success_count}")
    print(f"Errors: {error_count}")
    if errors:
        print("\nErrors:")
        for name, err in errors:
            print(f"  {name}: {err}")

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
