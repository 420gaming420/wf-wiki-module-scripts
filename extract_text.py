#!/usr/bin/env python3
"""
extract_text.py — Extract wiki page text content from downloaded HTML files.

Reads HTML files from data/html/, converts the main content to Markdown
using markdownify, and saves them as <name>.md with corresponding metadata.

Unlike extract_lua.py which only extracts <pre> code blocks, this script
converts the full page content (headings, paragraphs, lists, tables, links,
code blocks) to readable Markdown format.

Usage:
    python extract_text.py [--config CONFIG] [--force]
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from markdownify import markdownify


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
    result["markdown_dir"] = Path(config.get("paths", "markdown_dir", fallback="data/markdown"))
    result["base_url"] = config.get("wiki", "base_url", fallback="https://wiki.warframe.com").rstrip("/")
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


def save_md_meta(markdown_dir: Path, module_name: str, metadata: dict) -> None:
    """
    Save metadata for a markdown extraction.

    Args:
        markdown_dir: Directory to save metadata in
        module_name: Module title
        metadata: Metadata dict to save
    """
    safe_name = module_name.replace(":", "-").replace("/", "-")
    meta_path = markdown_dir / f"{safe_name}.meta.json"

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)


def is_stale(html_meta: dict | None, md_meta: dict | None, staleness_hours: int) -> bool:
    """
    Check if markdown extraction is stale and needs re-extraction.

    Args:
        html_meta: HTML metadata dict or None
        md_meta: Markdown metadata dict or None
        staleness_hours: Minimum hours between extractions

    Returns:
        True if file should be re-extracted
    """
    # Missing HTML metadata
    if html_meta is None:
        return False

    # Missing markdown file or metadata
    if md_meta is None:
        return True

    # Wiki timestamp changed
    if html_meta.get("wiki_timestamp") != md_meta.get("wiki_timestamp"):
        return True

    # Timestamps match — file is up to date
    return False


def extract_title(html: str) -> str:
    """
    Extract the page title from HTML.

    Args:
        html: Raw HTML string

    Returns:
        Page title string
    """
    match = re.search(r"<title>(.*?)</title>", html)
    if match:
        title = match.group(1)
        # Remove " - WARFRAME Wiki" suffix
        title = re.sub(r"\s*-\s*WARFRAME\s*Wiki\s*$", "", title, flags=re.IGNORECASE)
        return title.strip()
    return ""


def clean_pre_block(html: str) -> str:
    """
    Clean a <pre> block by removing line-number spans and decoding entities.

    MediaWiki highlights Lua code with <span id="L-N"> line number wrappers.
    This strips those wrappers while preserving the actual code content.

    Args:
        html: Raw HTML content of a <pre> block

    Returns:
        Cleaned text content
    """
    # Remove line number anchor spans: <span id="L-N"><a href="#L-N">...</a></span>
    html = re.sub(r'<span id="L-\d+"[^>]*>.*?</span>', "", html, flags=re.DOTALL)
    # Remove standalone line number spans: <span class="linenos">...</span>
    html = re.sub(r'<span class="linenos"[^>]*>.*?</span>', "", html, flags=re.DOTALL)
    # Remove comment class spans: <span class="c1">...</span> -> just content
    html = re.sub(r'<span class="c\d+"[^>]*>(.*?)</span>', r"\1", html, flags=re.DOTALL)
    # Remove any remaining span tags
    html = re.sub(r"<span[^>]*>", "", html)
    html = re.sub(r"</span>", "", html)
    # Decode common HTML entities
    html = html.replace("&#39;", "'").replace("&amp;", "&")
    html = html.replace("&lt;", "<").replace("&gt;", ">")
    html = html.replace("&quot;", '"')
    return html


def html_to_markdown(html: str, page_title: str, base_url: str) -> str:
    """
    Convert MediaWiki HTML content to Markdown.

    Extracts the mw-parser-output div, strips scripts/styles,
    cleans pre blocks, then converts to markdown.

    Args:
        html: Full HTML document
        page_title: Page title for frontmatter
        base_url: Wiki base URL for frontmatter

    Returns:
        Markdown string
    """
    # Extract the main content div
    match = re.search(
        r'<div class="mw-content-ltr mw-parser-output"[^>]*>(.*?)</div>'
        r'\s*(?:<div id="catlinks|<div class="printfooter|<script|</body>)',
        html,
        re.DOTALL,
    )
    if not match:
        return ""

    content = match.group(1)

    # Strip style and script tags
    content = re.sub(r"<style[^>]*>.*?</style>", "", content, flags=re.DOTALL)
    content = re.sub(r"<script[^>]*>.*?</script>", "", content, flags=re.DOTALL)

    # Clean pre blocks before markdown conversion
    content = re.sub(r"<pre[^>]*>(.*?)</pre>", lambda m: f"<pre>{clean_pre_block(m.group(1))}</pre>", content, flags=re.DOTALL)

    # Convert to markdown (all code blocks are Lua)
    md = markdownify(content, heading_style="ATX", code_language="lua", strip=["script", "style"])

    # Clean up excessive blank lines
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = md.strip() + "\n"

    return md


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Extract wiki page text as Markdown from HTML files")
    parser.add_argument("--config", type=Path, default=Path("config.ini"), help="Path to config file")
    parser.add_argument("--force", action="store_true", help="Force re-extraction of all modules")
    args = parser.parse_args()

    # Load configuration
    config = load_config(args.config)

    # Create directories
    config["markdown_dir"].mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("WARFRAME Wiki Markdown Extractor")
    print("=" * 60)
    print(f"HTML directory: {config['html_dir']}")
    print(f"Markdown directory: {config['markdown_dir']}")
    print(f"Base URL: {config['base_url']}")
    print(f"Staleness threshold: {config['staleness_hours']} hours")
    print()

    start_time = time.time()

    # Find all HTML files
    html_files = sorted(config["html_dir"].glob("*.html"))
    print(f"Found {len(html_files)} HTML files")
    print()

    # Pre-filter: only process files that need re-extraction
    files_to_process = []
    skip_count = 0

    for html_path in html_files:
        safe_name = html_path.stem
        if safe_name.startswith("Module-"):
            suffix = safe_name[7:]
            module_name = f"Module:{suffix.replace('-', '/')}"
        else:
            module_name = safe_name.replace('-', '/')

        html_meta = load_html_meta(config["html_dir"], module_name)
        md_meta = load_html_meta(config["markdown_dir"], module_name)

        if not args.force and not is_stale(html_meta, md_meta, config["staleness_hours"]):
            skip_count += 1
            continue
        files_to_process.append((html_path, module_name, html_meta, md_meta))

    print(f"Files to process: {len(files_to_process)} (skipping {skip_count} up-to-date)")
    print()

    # Process each HTML file
    success_count = 0
    error_count = 0

    for i, (html_path, module_name, html_meta, md_meta) in enumerate(files_to_process, 1):
        safe_name = html_path.stem
        print(f"[{i}/{len(files_to_process)}] Processing: {module_name}")

        # Read HTML
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                html_content = f.read()
        except OSError as e:
            print(f"  Error: Failed to read {html_path}: {e}")
            error_count += 1
            continue

        # Extract title
        page_title = extract_title(html_content)

        # Convert to markdown
        try:
            md_content = html_to_markdown(html_content, page_title, config["base_url"])
        except Exception as e:
            print(f"  Error: Failed to convert {html_path}: {e}")
            error_count += 1
            continue

        if not md_content:
            metadata = {
                "page": module_name,
                "wiki_timestamp": html_meta.get("wiki_timestamp") if html_meta else None,
                "extracted_at": datetime.now(timezone.utc).isoformat(),
                "file_size": 0,
                "status": "fail"
            }
            save_md_meta(config["markdown_dir"], module_name, metadata)
            print(f"  Skipped (no content)")
            skip_count += 1
            continue

        # Save markdown
        md_filename = f"{safe_name}.md"
        md_path = config["markdown_dir"] / md_filename
        try:
            with open(md_path, "w", encoding="utf-8") as f:
                # Write frontmatter
                wiki_url = f"{config['base_url']}/w/{module_name.replace(':', '/').replace('/', '/')}"
                # Normalize wiki URL
                wiki_path = module_name.replace(":", "/", 1)
                wiki_url = f"{config['base_url']}/w/{wiki_path}"
                f.write(f"---\n")
                f.write(f"title: \"{page_title}\"\n")
                f.write(f"wiki_url: \"{wiki_url}\"\n")
                f.write(f"wiki_timestamp: \"{html_meta.get('wiki_timestamp', '')}\"\n")
                f.write(f"---\n")
                f.write(f"\n")
                f.write(md_content)
                f.write(f"\n")
        except OSError as e:
            print(f"  Error: Failed to save {md_path}: {e}")
            error_count += 1
            continue

        # Save metadata
        metadata = {
            "page": module_name,
            "wiki_timestamp": html_meta.get("wiki_timestamp") if html_meta else None,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "file_size": len(md_content.encode("utf-8")),
            "status": "success",
        }
        save_md_meta(config["markdown_dir"], module_name, metadata)

        print(f"  Success! Saved to {md_path} ({len(md_content)} chars)")
        success_count += 1

    # Summary
    elapsed = time.time() - start_time
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total HTML files: {len(html_files)}")
    print(f"Files processed:  {len(files_to_process)}")
    print(f"Extracted: {success_count}")
    print(f"Skipped: {skip_count}")
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
