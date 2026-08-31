#!/usr/bin/env python3
"""
extract_lua.py — Extract Lua source code from downloaded HTML files.

Reads HTML files from data/html/, extracts all Lua code blocks (including
examples and schemas), and saves them as <name>_N.lua with corresponding metadata.

Usage:
    python extract_lua.py [--config CONFIG] [--force]
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from utils import lua_extractor


def load_config(config_path: Path) -> dict:
    """
    Load configuration from config.ini.

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
    result["html_dir"] = Path(config.get("paths", "html_dir", fallback="data/html"))
    result["lua_dir"] = Path(config.get("paths", "lua_dir", fallback="data/lua"))
    result["staleness_hours"] = _parse_int(config, "wiki", "staleness_hours", 24)

    return result


def _parse_int(config, section: str, key: str, default: int) -> int:
    """Parse an integer value from config with error handling."""
    try:
        return int(config.get(section, key, fallback=default))
    except (ValueError, TypeError):
        print(f"Warning: Invalid integer for [{section}] {key}, using default: {default}")
        return default


def load_html_meta(html_dir: Path, module_name: str) -> dict | None:
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


def save_lua_meta(lua_dir: Path, module_name: str, metadata: dict) -> None:
    """
    Save metadata for a Lua extraction.

    Args:
        lua_dir: Directory to save metadata in
        module_name: Module title
        metadata: Metadata dict to save
    """
    safe_name = module_name.replace(":", "-").replace("/", "-")
    meta_path = lua_dir / f"{safe_name}.meta.json"

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)


def is_stale(html_meta: dict | None, lua_meta: dict | None, staleness_hours: int) -> bool:
    """
    Check if Lua extraction is stale and needs re-extraction.

    Args:
        html_meta: HTML metadata dict or None
        lua_meta: Lua metadata dict or None
        staleness_hours: Minimum hours between extractions

    Returns:
        True if file should be re-extracted
    """
    # Missing HTML metadata
    if html_meta is None:
        return False

    # Missing Lua file or metadata
    if lua_meta is None:
        return True

    # Wiki timestamp changed
    if html_meta.get("wiki_timestamp") != lua_meta.get("wiki_timestamp"):
        return True

    # Check staleness threshold
    extracted_at = lua_meta.get("extracted_at")
    if extracted_at:
        try:
            extracted_time = datetime.fromisoformat(extracted_at.replace("Z", "+00:00"))
            hours_since = (datetime.now(timezone.utc) - extracted_time).total_seconds() / 3600
            if hours_since < staleness_hours:
                return False
        except ValueError:
            pass

    return True


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Extract Lua source from downloaded HTML files")
    parser.add_argument("--config", type=Path, default=Path("config.ini"), help="Path to config file")
    parser.add_argument("--force", action="store_true", help="Force re-extraction of all modules")
    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)

    # Create directories
    config["lua_dir"].mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("WARFRAME Wiki Lua Extractor")
    print("=" * 60)
    print(f"HTML directory: {config['html_dir']}")
    print(f"Lua directory: {config['lua_dir']}")
    print(f"Staleness threshold: {config['staleness_hours']} hours")
    print()

    start_time = time.time()

    # Find all HTML files
    html_files = sorted(config["html_dir"].glob("*.html"))
    print(f"Found {len(html_files)} HTML files")
    print()

    # Process each HTML file
    success_count = 0
    skip_count = 0
    error_count = 0

    for i, html_path in enumerate(html_files, 1):
        # Extract module name from filename
        # safe_name is like "Module-Ability-data" -> "Module:Ability/data"
        safe_name = html_path.stem  # e.g., "Module-Ability-data"
        if safe_name.startswith("Module-"):
            suffix = safe_name[7:]  # Remove "Module-"
            module_name = f"Module:{suffix.replace('-', '/')}"
        else:
            module_name = safe_name.replace('-', '/')

        print(f"[{i}/{len(html_files)}] Processing: {module_name}")

        # Load metadata
        html_meta = load_html_meta(config["html_dir"], module_name)
        lua_meta = load_html_meta(config["lua_dir"], module_name)

        # Check staleness
        if not args.force and not is_stale(html_meta, lua_meta, config["staleness_hours"]):
            print(f"  Skipped (up-to-date)")
            skip_count += 1
            continue

        # Read HTML
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                html_content = f.read()
        except OSError as e:
            print(f"  Error: Failed to read {html_path}: {e}")
            error_count += 1
            continue

        # Extract all Lua blocks and combined comments
        blocks, comments = lua_extractor.extract_all(html_content)

        if not blocks:
            print(f"  Warning: No Lua code found in {html_path}")
            error_count += 1
            continue

        # Save each block as a separate file: <safe_name>_N.lua
        lua_files = []
        total_bytes = 0
        for block_idx, block_code in enumerate(blocks):
            lua_filename = f"{safe_name}_{block_idx}.lua"
            lua_path = config["lua_dir"] / lua_filename
            try:
                with open(lua_path, "w", encoding="utf-8") as f:
                    f.write(block_code)
                total_bytes += len(block_code)
                lua_files.append(lua_filename)
            except OSError as e:
                print(f"  Error: Failed to save {lua_path}: {e}")
                error_count += 1
                continue

        # Save metadata
        metadata = {
            "page": module_name,
            "wiki_timestamp": html_meta.get("wiki_timestamp") if html_meta else None,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "lua_files": lua_files,
            "lua_block_count": len(blocks),
            "file_size": total_bytes,
            "comment_count": len(comments.splitlines()) if comments else 0,
            "status": "success"
        }
        save_lua_meta(config["lua_dir"], module_name, metadata)

        print(f"  Success! Saved {len(blocks)} block(s) to {config['lua_dir']} ({total_bytes} bytes, {len(comments.splitlines()) if comments else 0} comments)")
        success_count += 1

    # Summary
    elapsed = time.time() - start_time
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total HTML files: {len(html_files)}")
    print(f"Extracted: {success_count}")
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
