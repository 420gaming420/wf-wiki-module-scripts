#!/usr/bin/env python3
"""
Wiki Client - Shared HTTP client for WARFRAME Wiki requests.

Provides rate-limited fetching for both API JSON and HTML pages.
Hard-coded minimum rate limit of 1 second to avoid IP bans.
"""

import json
import time
import urllib.error
import urllib.request
from typing import Any

# Hard-coded minimum rate limit to avoid IP bans
MIN_RATE_LIMIT_SECONDS = 1.0

# Global state for rate limiting and user agent
_rate_limit_seconds: float = MIN_RATE_LIMIT_SECONDS
_user_agent: str = "WFModuleMirror/1.0"


def configure(rate_limit: float, user_agent: str) -> None:
    """
    Set global rate limit and user agent for all wiki requests.

    Args:
        rate_limit: Minimum seconds between requests (will be clamped to MIN_RATE_LIMIT_SECONDS)
        user_agent: User-Agent header value for HTTP requests
    """
    global _rate_limit_seconds, _user_agent
    _rate_limit_seconds = max(float(rate_limit), MIN_RATE_LIMIT_SECONDS)
    _user_agent = user_agent


def get_rate_limit() -> float:
    """
    Get the current rate limit in seconds.

    Returns:
        Current rate limit (never less than MIN_RATE_LIMIT_SECONDS)
    """
    return _rate_limit_seconds


def get_user_agent() -> str:
    """
    Get the current user agent string.

    Returns:
        User-Agent header value
    """
    return _user_agent


# Tracks time of last request to enforce rate limiting
_last_request_time: float = 0.0


def _wait_for_rate_limit() -> None:
    """Wait until the minimum rate limit interval has passed."""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _rate_limit_seconds:
        wait_time = _rate_limit_seconds - elapsed
        time.sleep(wait_time)
    _last_request_time = time.time()


def fetch_html(url: str, max_retries: int = 3) -> str | None:
    """
    Fetch an HTML page from the wiki with rate limiting, gzip, and retries.

    Args:
        url: Full URL to the wiki page
        max_retries: Maximum retry attempts on failure

    Returns:
        HTML content string, or None if fetch failed after all retries
    """
    for attempt in range(1, max_retries + 1):
        _wait_for_rate_limit()

        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": _user_agent,
                    "Accept-Encoding": "gzip",
                }
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                content = resp.read()

                # Handle gzip compression
                content_type = resp.headers.get("Content-Encoding", "")
                if "gzip" in content_type:
                    import gzip
                    content = gzip.decompress(content)

                return content.decode("utf-8")

        except urllib.error.HTTPError as e:
            if e.code == 429:  # Rate limited
                wait_time = 10 * attempt
                print(f"  Rate limited (attempt {attempt}/{max_retries}), waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            else:
                print(f"  HTTP error {e.code} for {url}: {e.reason}")
                if attempt == max_retries:
                    return None
                time.sleep(2 ** attempt)

        except urllib.error.URLError as e:
            print(f"  URL error (attempt {attempt}/{max_retries}) for {url}: {e.reason}")
            if attempt == max_retries:
                return None
            time.sleep(2 ** attempt)

    return None


def fetch_api_json(url: str, max_retries: int = 3) -> dict | None:
    """
    Fetch a JSON response from the wiki API with rate limiting and retries.

    Args:
        url: Full API URL
        max_retries: Maximum retry attempts on failure

    Returns:
        Parsed JSON dict, or None if fetch failed after all retries
    """
    for attempt in range(1, max_retries + 1):
        _wait_for_rate_limit()

        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": _user_agent,
                    "Accept-Encoding": "gzip",
                    "Accept": "application/json",
                }
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                content = resp.read()

                # Handle gzip compression
                content_type = resp.headers.get("Content-Encoding", "")
                if "gzip" in content_type:
                    import gzip
                    content = gzip.decompress(content)

                data = json.loads(content.decode("utf-8"))

                # Check for API errors
                if "error" in data:
                    error_code = data["error"].get("code", "unknown")
                    if error_code == "ratelimited":
                        print(f"  Rate limit hit, waiting 10s...")
                        time.sleep(10)
                        continue
                    else:
                        print(f"  API error: {error_code}")
                        if attempt == max_retries:
                            return None
                        time.sleep(2 ** attempt)
                        continue

                return data

        except urllib.error.HTTPError as e:
            if e.code == 429:  # Rate limited
                wait_time = 10 * attempt
                print(f"  Rate limited (attempt {attempt}/{max_retries}), waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            else:
                print(f"  HTTP error {e.code} for {url}: {e.reason}")
                if attempt == max_retries:
                    return None
                time.sleep(2 ** attempt)

        except urllib.error.URLError as e:
            print(f"  URL error (attempt {attempt}/{max_retries}) for {url}: {e.reason}")
            if attempt == max_retries:
                return None
            time.sleep(2 ** attempt)

        except json.JSONDecodeError as e:
            print(f"  JSON decode error (attempt {attempt}/{max_retries}): {e}")
            if attempt == max_retries:
                return None
            time.sleep(2 ** attempt)

    return None
