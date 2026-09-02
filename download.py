#!/usr/bin/env python3
"""
download.py — Download WARFRAME Wiki module HTML pages for archival.

Downloads HTML files for all actual modules (excluding sandbox),
storing them in data/html/ with corresponding metadata.

Uses cached data from request.py (all_wfwiki_modules_merged.json and all_timestamps.json).
No API requests are made by this script.

Usage:
    python download.py [--config CONFIG] [--force] [--page NAME]
"""

import argparse
import json
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from utils import wiki_client
from utils import lua_extractor


def load_config(config_path: Path) -> dict:
    """
    Load configuration from config.ini with improved parsing.

    Args:
        config_path: Path to config file

    Returns:
        Dict of configuration values
    """
    import configparser

    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    config = configparser.ConfigParser()
    config.read(config_path)

    result = {}

    # Wiki settings
    result["base_url"] = config.get("wiki", "base_url", fallback="https://wiki.warframe.com").rstrip("/")
    result["staleness_hours"] = _parse_int(config, "wiki", "staleness_hours", 24)
    result["rate_limit"] = _parse_float(config, "wiki", "rate_limit", 1.0)

    # User agents (one per tool)
    result["user_agent_wiki"] = config.get("user_agents", "wiki_client", fallback="WFModuleMirror/1.0")
    result["user_agent_download"] = config.get("user_agents", "download", fallback="WFModuleDownload/1.0")
    result["user_agent_attribution"] = config.get("user_agents", "attribution", fallback="WFModuleAttribution/1.0")

    # Paths
    result["html_dir"] = Path(config.get("paths", "html_dir", fallback="data/html"))
    result["lua_dir"] = Path(config.get("paths", "lua_dir", fallback="data/lua"))
    result["json_dir"] = Path(config.get("paths", "output_dir", fallback="data/json"))
    result["catalog_file"] = Path(config.get("paths", "catalog_file", fallback="all_wfwiki_modules_merged.json"))
    result["timestamps_file"] = Path(config.get("paths", "timestamps_file", fallback="all_timestamps.json"))
    result["log_dir"] = Path(config.get("paths", "log_dir", fallback="data/logs"))

    return result


def _parse_int(config, section: str, key: str, default: int) -> int:
    """Parse an integer value from config with error handling."""
    try:
        return int(config.get(section, key, fallback=default))
    except (ValueError, TypeError):
        print(f"Warning: Invalid integer for [{section}] {key}, using default: {default}")
        return default


def _parse_float(config, section: str, key: str, default: float) -> float:
    """Parse a float value from config with error handling."""
    try:
        return float(config.get(section, key, fallback=default))
    except (ValueError, TypeError):
        print(f"Warning: Invalid float for [{section}] {key}, using default: {default}")
        return default


def filter_modules(modules: list) -> list:
    """
    Filter out sandbox modules.

    Args:
        modules: List of module dicts from wiki API

    Returns:
        Filtered list excluding sandbox modules
    """
    return [
        m for m in modules
        if "sandbox" not in m["title"].lower()
    ]


def load_meta(html_dir: Path, module_name: str) -> dict | None:
    """
    Load metadata for a module from its .meta.json file.

    Args:
        html_dir: Directory containing HTML files
        module_name: Module title

    Returns:
        Metadata dict or None if not found
    """
    safe_name = module_name.replace(":", "-").replace("/", "-")
    meta_path = html_dir / f"{safe_name}.meta.json"

    if not meta_path.exists():
        return None

    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_meta(html_dir: Path, module_name: str, metadata: dict) -> None:
    """
    Save metadata for a module.

    Args:
        html_dir: Directory to save metadata in
        module_name: Module title
        metadata: Metadata dict to save
    """
    safe_name = module_name.replace(":", "-").replace("/", "-")
    meta_path = html_dir / f"{safe_name}.meta.json"

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)


def is_stale(meta: dict | None, cached_timestamp: str, staleness_hours: int) -> bool:
    """
    Check if a module HTML file is stale and needs re-downloading.

    Args:
        meta: Existing metadata dict or None
        cached_timestamp: Cached wiki timestamp from all_timestamps.json
        staleness_hours: Minimum hours between downloads

    Returns:
        True if file should be re-downloaded
    """
    # Missing file or metadata
    if meta is None:
        return True

    # Wiki timestamp changed
    if meta.get("wiki_timestamp") != cached_timestamp:
        return True

    # Timestamps match — file is up to date
    return False


def module_to_url(base_url: str, module_name: str) -> str:
    """
    Convert module name to wiki URL.

    Args:
        base_url: Wiki base URL
        module_name: Module title

    Returns:
        Full URL to the wiki page
    """
    return f"{base_url}/w/{urllib.parse.quote(module_name, safe=':/')}"


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Download WARFRAME Wiki module HTML pages")
    parser.add_argument("--config", type=Path, default=Path("config.ini"), help="Path to config file")
    parser.add_argument("--force", action="store_true", help="Force re-download all modules")
    parser.add_argument("--page", type=str, help="Download only a single module (for testing)")
    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)

    # Configure wiki client
    wiki_client.configure(config["rate_limit"], config["user_agent_download"])

    # Create directories
    config["html_dir"].mkdir(parents=True, exist_ok=True)
    config["log_dir"].mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("WARFRAME Wiki HTML Downloader")
    print("=" * 60)
    print(f"Base URL: {config['base_url']}")
    print(f"HTML directory: {config['html_dir']}")
    print(f"Rate limit: {config['rate_limit']}s")
    print(f"Staleness threshold: {config['staleness_hours']} hours")
    print()

    # Verify cache files exist
    catalog_path = config["catalog_file"]
    timestamps_path = config["timestamps_file"]

    if not catalog_path.exists():
        print(f"Error: Module catalog not found: {catalog_path}")
        print("Run request.py first to generate the catalog.")
        sys.exit(1)

    if not timestamps_path.exists():
        print(f"Error: Timestamp cache not found: {timestamps_path}")
        print("Run request.py first to generate the timestamp cache.")
        sys.exit(1)

    print(f"Using cached module catalog: {catalog_path}")
    print(f"Using cached timestamps: {timestamps_path}")
    print()

    # Load module catalog from cache (no API calls)
    with open(catalog_path, "r", encoding="utf-8") as f:
        modules = json.load(f)

    # Load timestamps from cache (no API calls)
    with open(timestamps_path, "r", encoding="utf-8") as f:
        timestamps_data = json.load(f)
    timestamps = {t["title"]: t["timestamp"] for t in timestamps_data}

    print(f"Loaded {len(modules)} modules from catalog")
    print(f"Loaded {len(timestamps)} timestamps from cache")
    print()

    start_time = time.time()

    # Filter out sandbox
    modules = filter_modules(modules)
    print(f"Total modules to process (after filtering): {len(modules)}")

    # If --page specified, only download that one
    if args.page:
        modules = [m for m in modules if m["title"] == args.page]
        if not modules:
            print(f"Module '{args.page}' not found in catalog")
            sys.exit(1)
        print(f"Downloading single module: {args.page}")
    print()

    # Pre-filter: only process modules that need downloading
    modules_to_download = []
    skip_count = 0

    for module in modules:
        module_name = module["title"]
        cached_timestamp = timestamps.get(module_name)
        if not cached_timestamp:
            continue
        meta = load_meta(config["html_dir"], module_name)
        if not args.force and not is_stale(meta, cached_timestamp, config["staleness_hours"]):
            skip_count += 1
            continue
        modules_to_download.append(module)

    print(f"Modules to download: {len(modules_to_download)} (skipping {skip_count} up-to-date)")
    print()

    # Download modules
    success_count = 0
    error_count = 0

    for i, module in enumerate(modules_to_download, 1):
        module_name = module["title"]
        print(f"[{i}/{len(modules_to_download)}] Processing: {module_name}")

        # Get timestamp from cache (no API call)
        cached_timestamp = timestamps.get(module_name)
        if not cached_timestamp:
            print(f"  Warning: No timestamp for {module_name}, skipping")
            error_count += 1
            continue

        # Download HTML
        url = module_to_url(config["base_url"], module_name)
        print(f"  Downloading: {url}")

        html_content = wiki_client.fetch_html(url)
        if not html_content:
            print(f"  Error: Failed to download {module_name}")
            error_count += 1
            continue

        # Save HTML
        safe_name = module_name.replace(":", "-").replace("/", "-")
        html_path = config["html_dir"] / f"{safe_name}.html"

        try:
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
        except OSError as e:
            print(f"  Error: Failed to save {html_path}: {e}")
            error_count += 1
            continue

        # Save metadata
        metadata = {
            "page": module_name,
            "wiki_timestamp": cached_timestamp,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "file_size": len(html_content),
            "status": "success"
        }
        save_meta(config["html_dir"], module_name, metadata)

        print(f"  Success! Saved to {html_path} ({len(html_content)} bytes)")
        success_count += 1

        # Small delay between downloads (rate limiter handles this, but add buffer)
        time.sleep(0.1)

    # Summary
    elapsed = time.time() - start_time
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total modules: {len(modules)}")
    print(f"Downloaded: {success_count}")
    print(f"Skipped (up-to-date): {skip_count}")
    print(f"Errors: {error_count}")
    print(f"Time elapsed: {elapsed:.2f} seconds")
    print("=" * 60)

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
