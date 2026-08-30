#!/usr/bin/env python3
"""
WARFRAME Wiki Module Request Script

Queries the MediaWiki API to determine which local module copies are stale
and need to be updated via Puppeteer conversion.

Usage:
    python request.py [--config CONFIG] [--force-collect]
"""

import argparse
import configparser
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote


def load_config(config_path: Path) -> configparser.ConfigParser:
    """
    Load configuration from INI file.

    Args:
        config_path: Path to config file

    Returns:
        ConfigParser instance
    """
    config = configparser.ConfigParser()
    if config_path.exists():
        config.read(config_path)
    else:
        print(f"Warning: Config file not found at {config_path}")
        print("Using default values.")
    
    return config


def get_config_value(config: configparser.ConfigParser, section: str, key: str, default=None):
    """Get a config value with fallback to default."""
    if config.has_option(section, key):
        value = config.get(section, key)
        # Try to convert to appropriate type
        if default is not None:
            if isinstance(default, bool):
                return value.lower() in ('true', '1', 'yes')
            elif isinstance(default, int):
                return int(value)
            elif isinstance(default, float):
                return float(value)
        return value
    return default


class RateLimiter:
    """Rate limiter to control API request frequency."""
    
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self.last_request_time = 0.0
    
    def wait(self):
        """Wait until the minimum interval has passed."""
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.min_interval:
            wait_time = self.min_interval - elapsed
            time.sleep(wait_time)
        self.last_request_time = time.time()


def make_api_request(url: str, headers: dict, rate_limiter: RateLimiter, max_retries: int = 3) -> dict:
    """
    Make API request with rate limiting and retry logic.

    Args:
        url: Request URL
        headers: Request headers
        rate_limiter: RateLimiter instance
        max_retries: Maximum retry attempts

    Returns:
        Parsed JSON response

    Raises:
        Exception: On persistent failures
    """
    for attempt in range(1, max_retries + 1):
        rate_limiter.wait()
        
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                content = response.read()
                
                # Handle gzip compression
                content_type = response.headers.get('Content-Encoding', '')
                if 'gzip' in content_type:
                    import gzip
                    content = gzip.decompress(content)
                
                data = json.loads(content.decode('utf-8'))
                
                # Check for API errors
                if 'error' in data:
                    error_code = data['error'].get('code', 'unknown')
                    if error_code == 'ratelimited':
                        print(f"  Rate limit hit, waiting 10s...")
                        time.sleep(10)
                        continue
                    else:
                        raise Exception(f"API error: {error_code}")
                
                return data
                
        except urllib.error.HTTPError as e:
            if e.code == 429:  # Rate limited
                wait_time = 10 * attempt
                print(f"  Rate limited (attempt {attempt}/{max_retries}), waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            else:
                raise Exception(f"HTTP error {e.code}: {e.reason}")
                
        except urllib.error.URLError as e:
            wait_time = 2 ** attempt
            print(f"  URL error (attempt {attempt}/{max_retries}): {e.reason}, waiting {wait_time}s...")
            time.sleep(wait_time)
            continue
            
        except json.JSONDecodeError as e:
            wait_time = 2 ** attempt
            print(f"  JSON decode error (attempt {attempt}/{max_retries}), waiting {wait_time}s...")
            time.sleep(wait_time)
            continue
    
    raise Exception(f"Failed after {max_retries} attempts")


def collect_module_catalog(api_url: str, user_agent: str, rate_limiter: RateLimiter) -> list:
    """
    Collect all Module namespace pages from the wiki.

    Args:
        api_url: Wiki API URL
        user_agent: User-Agent header
        rate_limiter: RateLimiter instance

    Returns:
        List of page dictionaries
    """
    all_pages = []
    apcontinue = None
    request_num = 0
    
    print("\nCollecting module catalog from wiki...")
    
    while True:
        request_num += 1
        
        params = {
            'action': 'query',
            'list': 'allpages',
            'apnamespace': '828',
            'aplimit': '420',
            'format': 'json'
        }
        
        if apcontinue:
            params['apcontinue'] = apcontinue
        
        # Build query string
        query_parts = []
        for key, value in params.items():
            if value is not None:
                query_parts.append(f"{key}={value}")
        query_string = '&'.join(query_parts)
        url = f"{api_url}?{query_string}"
        
        print(f"  Request {request_num}: ", end='', flush=True)
        data = make_api_request(url, {'User-Agent': user_agent, 'Accept-Encoding': 'gzip'}, rate_limiter)
        
        if 'query' not in data or 'allpages' not in data['query']:
            raise Exception(f"Invalid response structure in request {request_num}")
        
        pages = data['query']['allpages']
        page_count = len(pages)
        all_pages.extend(pages)
        
        # Check for continuation
        has_continue = 'continue' in data
        if has_continue:
            apcontinue = data['continue'].get('apcontinue')
        else:
            apcontinue = None
        
        print(f"{page_count} pages (total: {len(all_pages)})")
        
        if not has_continue:
            break
        
        print(f"  Waiting 1s before next request...")
        time.sleep(1)
    
    print(f"\n  Collected {len(all_pages)} total modules")
    return all_pages


def get_module_timestamps(titles: list, api_url: str, user_agent: str, rate_limiter: RateLimiter, max_retries: int = 3) -> dict:
    """
    Get timestamps for multiple modules using batched API requests.

    Args:
        titles: List of module titles
        api_url: Wiki API URL
        user_agent: User-Agent header
        rate_limiter: RateLimiter instance
        max_retries: Maximum retry attempts

    Returns:
        Dict mapping title -> {timestamp, revid, pageid}
    """
    results = {}
    batch_size = 50
    total_batches = (len(titles) + batch_size - 1) // batch_size

    print(f"\nFetching timestamps for {len(titles)} modules...")

    for batch_start in range(0, len(titles), batch_size):
        batch_titles = [t for t in titles[batch_start:batch_start + batch_size] if isinstance(t, str)]
        batch_num = (batch_start // batch_size) + 1

        encoded_titles = '|'.join(quote(t, safe='') for t in batch_titles)
        url = (
            f"{api_url}?action=query"
            f"&titles={encoded_titles}"
            f"&prop=revisions"
            f"&rvprop=timestamp|ids"
            f"&format=json"
        )

        print(f"  Batch {batch_num}/{total_batches}: {len(batch_titles)} modules", end='', flush=True)

        try:
            data = make_api_request(url, {'User-Agent': user_agent, 'Accept-Encoding': 'gzip'}, rate_limiter, max_retries)

            pages_data = data.get('query', {}).get('pages', {})
            batch_results = 0

            for page in pages_data.values():
                page_title = page.get('title', '')
                if page_title in batch_titles:
                    if 'revisions' in page:
                        revision = page['revisions'][0]
                        results[page_title] = {
                            'title': page_title,
                            'pageid': page.get('pageid'),
                            'revid': revision['revid'],
                            'timestamp': revision['timestamp']
                        }
                        batch_results += 1

            print(f" - Found {batch_results}/{len(batch_titles)} modules")

        except Exception as e:
            print(f" - Error: {e}")

    print(f"\n  Retrieved timestamps for {len(results)}/{len(titles)} modules")
    return results


def load_ignore_list(ignore_path: Path) -> set:
    """
    Load ignored modules from JSON file.

    Args:
        ignore_path: Path to ignore_modules.json

    Returns:
        Set of ignored module titles
    """
    if not ignore_path.exists():
        return set()
    
    try:
        with open(ignore_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        ignored = set()
        if isinstance(data, list):
            ignored = set(data)
        elif isinstance(data, dict) and 'ignored_modules' in data:
            ignored = set(mod['module'] for mod in data['ignored_modules'] if 'module' in mod)
        
        return ignored
        
    except (json.JSONDecodeError, KeyError) as e:
        print(f"Warning: Error loading ignore list: {e}")
        return set()


def load_metadata(metadata_dir: Path) -> dict:
    """
    Load existing metadata from .meta.json files.

    Args:
        metadata_dir: Directory containing metadata files

    Returns:
        Dict mapping page title -> metadata
    """
    metadata = {}
    
    if not metadata_dir.exists():
        return metadata
    
    for meta_file in metadata_dir.glob('*.meta.json'):
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if 'page' in data:
                metadata[data['page']] = data
                
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Error loading {meta_file.name}: {e}")
    
    return metadata


def filter_stale_modules(
    modules: list,
    timestamps: dict,
    metadata: dict,
    ignore_list: set,
    staleness_hours: int
) -> list:
    """
    Filter modules to find those with stale local copies.

    Args:
        modules: List of module dictionaries from API
        timestamps: Dict of wiki timestamps
        metadata: Dict of local metadata
        ignore_list: Set of ignored modules
        staleness_hours: Hours threshold for staleness

    Returns:
        List of modules with stale local copies
    """
    stale_modules = []
    now = datetime.now(timezone.utc)
    staleness_delta = timedelta(hours=staleness_hours)
    
    print(f"\nFiltering modules (staleness threshold: {staleness_hours} hours)...")
    
    for page in modules:
        title = page['title']
        
        # Skip ignored modules
        if title in ignore_list:
            continue
        
        # Get wiki timestamp
        wiki_ts = timestamps.get(title, {}).get('timestamp')
        if not wiki_ts:
            continue
        
        # Parse wiki timestamp
        try:
            wiki_datetime = datetime.fromisoformat(wiki_ts.replace('Z', '+00:00'))
        except ValueError:
            continue
        
        # Check local metadata
        local_meta = metadata.get(title)
        
        if local_meta:
            # Check if converted recently
            converted_at_str = local_meta.get('converted_at')
            if converted_at_str:
                try:
                    converted_at = datetime.fromisoformat(converted_at_str.replace('Z', '+00:00'))
                    if now - converted_at < staleness_delta:
                        # Converted recently, skip
                        continue
                except ValueError:
                    pass
            
            # Check if timestamp matches
            local_ts = local_meta.get('timestamp')
            if local_ts == wiki_ts:
                # Local copy is current, skip
                continue
        
        # Module is stale (new or needs update)
        reason = 'new_module' if not local_meta else 'timestamp_updated'
        
        stale_modules.append({
            'page': title,
            'reason': reason,
            'wiki_timestamp': wiki_ts,
            'pageid': page.get('pageid')
        })
    
    return stale_modules


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Query WARFRAME Wiki API for stale modules')
    parser.add_argument('--config', type=Path, default=Path('config.ini'), help='Path to config file')
    parser.add_argument('--force-collect', action='store_true', help='Force re-collection of module catalog')
    parser.add_argument('--check-metafiles', action='store_true', help='Check metadata files without API calls (dry run)')
    args = parser.parse_args()
    
    start_time = time.time()
    
    # Load configuration
    print("=" * 60)
    print("WARFRAME Wiki Module Request Script")
    print("=" * 60)
    
    config = load_config(args.config)
    
    # Debug: Show working directory and path info
    print(f"\n[CWD] Current working directory: {Path.cwd()}")
    print(f"[CWD] CWD absolute: {Path.cwd().resolve()}")
    
    api_url = get_config_value(config, 'wiki', 'api_url', 'https://wiki.warframe.com/api.php')
    user_agent = get_config_value(config, 'wiki', 'user_agent', 'WFModuleMirror/1.0')
    rate_limit_str = get_config_value(config, 'wiki', 'rate_limit', '1.0')
    rate_limit = float(rate_limit_str)
    staleness_hours = get_config_value(config, 'wiki', 'staleness_hours', 24)
    
    stale_modules_path = Path(get_config_value(config, 'paths', 'stale_modules', 'stale_modules.json'))
    ignore_modules_path = Path(get_config_value(config, 'paths', 'ignore_modules', 'ignore_modules.json'))
    metadata_dir = Path(get_config_value(config, 'paths', 'metadata_dir', 'data/json'))
    
    # Debug: Show metadata path info
    print(f"\n[METADATA_PATH] Config value: data/json")
    print(f"[METADATA_PATH] Resolved: {metadata_dir.resolve()}")
    print(f"[METADATA_PATH] Exists: {metadata_dir.exists()}")
    print(f"[METADATA_PATH] Is absolute: {metadata_dir.is_absolute()}")
    
    # Debug: Show directory contents
    print(f"\n[DEBUG] /tmp/scripts/ contents:")
    try:
        for f in Path('/tmp/scripts/').iterdir():
            print(f"  {f.name} ({'dir' if f.is_dir() else 'file'})")
    except Exception as e:
        print(f"  Error: {e}")
    
    print(f"\n[DEBUG] /tmp/scripts/data/ contents:")
    try:
        data_dir = Path('/tmp/scripts/data')
        if data_dir.exists():
            for f in data_dir.iterdir():
                print(f"  {f.name} -> {f.resolve() if f.is_symlink() else 'file'}")
        else:
            print("  Directory does not exist")
    except Exception as e:
        print(f"  Error: {e}")
    
    print(f"\n[DEBUG] /tmp/scripts/data/json/ contents:")
    try:
        json_dir = Path('/tmp/scripts/data/json')
        if json_dir.exists():
            meta_files = list(json_dir.glob('*.meta.json'))
            print(f"  Found {len(meta_files)} .meta.json files")
            if meta_files:
                print(f"  First 3 files:")
                for f in meta_files[:3]:
                    print(f"    {f.name}")
        else:
            print("  Directory does not exist")
    except Exception as e:
        print(f"  Error: {e}")
    
    rate_limiter = RateLimiter(min_interval=rate_limit)
    
    # --check-metafiles mode: skip all API calls, only check metadata files
    if args.check_metafiles:
        print(f"\n{'=' * 60}")
        print("CHECK-METAFILES MODE (dry run - no API calls)")
        print(f"{'=' * 60}")
        
        # Load ignore list (no API call)
        ignore_list = load_ignore_list(ignore_modules_path)
        if ignore_list:
            print(f"\nLoaded {len(ignore_list)} ignored modules")
        
        # Load metadata (no API call)
        print(f"\nLoading existing metadata from {metadata_dir}...")
        metadata = load_metadata(metadata_dir)
        print(f"  Found {len(metadata)} metadata files")
        
        print(f"\nConfig values:")
        print(f"  metadata_dir: {metadata_dir}")
        print(f"  resolved: {metadata_dir.resolve()}")
        print(f"  exists: {metadata_dir.exists()}")
        print(f"\nMetadata files found: {len(metadata)}")
        
        if metadata:
            print(f"\nFirst 3 metadata file contents:")
            for i, (page, data) in enumerate(list(metadata.items())[:3], 1):
                print(f"\n  {i}. {page}")
                print(f"     {json.dumps(data, indent=2)}")
        else:
            print("\n  No metadata files found!")
            print(f"\n  Trying alternative paths:")
            alt_paths = [
                Path('/tmp/scripts/data/json'),
                Path('/home/runner/work/wf-wiki-module-data/wf-wiki-module-data/json'),
                Path('json'),
            ]
            for alt in alt_paths:
                print(f"    {alt} -> exists: {alt.exists()}, files: {len(list(alt.glob('*.meta.json')) if alt.exists() else 0)}")
        
        print(f"\n{'=' * 60}")
        print("CHECK-METAFILES COMPLETE")
        print(f"{'=' * 60}")
        return 0
    
    # Phase 1: Collect module catalog
    catalog_path = Path('all_wfwiki_modules_merged.json')
    
    if args.force_collect or not catalog_path.exists():
        modules_data = collect_module_catalog(api_url, user_agent, rate_limiter)
        # Save catalog for future use
        with open(catalog_path, 'w', encoding='utf-8') as f:
            json.dump(modules_data, f, indent=2)
        print(f"\nSaved module catalog to {catalog_path}")
    else:
        print(f"\nUsing existing module catalog: {catalog_path}")
        with open(catalog_path, 'r', encoding='utf-8') as f:
            modules_data = json.load(f)
    
    # Phase 2: Load ignore list
    ignore_list = load_ignore_list(ignore_modules_path)
    if ignore_list:
        print(f"\nLoaded {len(ignore_list)} ignored modules")
    
    # Filter out ignored modules
    modules_to_check = [m for m in modules_data if m['title'] not in ignore_list]
    print(f"\nModules to check: {len(modules_to_check)} (after ignoring {len(ignore_list)})")

    # Filter out test and sandbox modules
    test_sand_modules = [
        m for m in modules_to_check
        if 'test' in m['title'].lower() or 'sandbox' in m['title'].lower()
    ]
    if test_sand_modules:
        print(f"\nExcluding {len(test_sand_modules)} test/sandbox modules")
        modules_to_check = [m for m in modules_to_check if m not in test_sand_modules]
    
    # Phase 3: Get timestamps
    module_titles = [m['title'] for m in modules_to_check]
    timestamps = get_module_timestamps(module_titles, api_url, user_agent, rate_limiter)
    
    # Phase 4: Load existing metadata
    print(f"\nLoading existing metadata from {metadata_dir}...")
    metadata = load_metadata(metadata_dir)
    print(f"  Found {len(metadata)} metadata files")
    
    # Phase 5: Filter stale modules
    stale_list = filter_stale_modules(modules_to_check, timestamps, metadata, ignore_list, staleness_hours)
    
    # Phase 6: Save stale modules
    print(f"\nSaving {len(stale_list)} stale modules to {stale_modules_path}...")
    with open(stale_modules_path, 'w', encoding='utf-8') as f:
        json.dump(stale_list, f, indent=2)
    
    # Summary
    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    print(f"Total modules: {len(modules_data)}")
    print(f"Ignored modules: {len(ignore_list)}")
    print(f"Modules checked: {len(modules_to_check)}")
    print(f"Modules with timestamps: {len(timestamps)}")
    print(f"Modules with metadata: {len(metadata)}")
    print(f"Stale modules (need update): {len(stale_list)}")
    print(f"Time elapsed: {elapsed:.2f} seconds")
    print(f"{'=' * 60}")
    
    if stale_list:
        print(f"\nStale modules saved to: {stale_modules_path}")
        print("\nFirst 5 stale modules:")
        for i, mod in enumerate(stale_list[:5], 1):
            print(f"  {i}. {mod['page']} ({mod['reason']})")
        if len(stale_list) > 5:
            print(f"  ... and {len(stale_list) - 5} more")
    
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
