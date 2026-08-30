#!/usr/bin/env python3
"""
Lua Extractor - Extract Lua code and comments from wiki HTML pages.

Provides functions to parse HTML and extract Lua source code blocks,
then parse comments from the Lua source.
"""

import re


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


def extract_all(html: str) -> tuple[str | None, str]:
    """
    Extract both Lua code and comments from HTML in one pass.

    Args:
        html: Raw HTML string

    Returns:
        Tuple of (lua_code or None, comments string)
    """
    lua_code = extract_lua_from_html(html)
    comments = extract_comments(lua_code) if lua_code else ""
    return lua_code, comments
