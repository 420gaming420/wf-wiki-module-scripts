#!/usr/bin/env python3
"""
Lua Extractor - Extract Lua code and comments from wiki HTML pages.

Provides functions to parse HTML and extract all Lua source code blocks
(including examples and schemas), then parse comments from the combined Lua source.
"""

import re


def extract_lua_blocks(html: str) -> list[str]:
    """
    Extract all Lua code blocks from a wiki HTML page.

    Finds every <pre> block in the HTML, cleans HTML entities,
    and returns them in document order (first block is index 0).

    Args:
        html: Raw HTML string

    Returns:
        List of cleaned Lua source code strings, one per <pre> block
    """
    pre_blocks = re.findall(r"<pre[^>]*>(.*?)</pre>", html, re.DOTALL)
    blocks = []
    for block in pre_blocks:
        clean = re.sub(r"<[^>]+>", "", block)
        clean = clean.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        clean = clean.replace("&quot;", '"').replace("&#39;", "'")
        blocks.append(clean)
    return blocks


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


def extract_all(html: str) -> tuple[list[str], str]:
    """
    Extract all Lua code blocks and comments from HTML in one pass.

    Concatenates all blocks with double-newline separators for comment
    extraction, then returns both the individual blocks and the combined
    comment text.

    Args:
        html: Raw HTML string

    Returns:
        Tuple of (list of lua code blocks, combined comments string)
    """
    blocks = extract_lua_blocks(html)
    combined = "\n\n".join(blocks) if blocks else ""
    comments = extract_comments(combined) if combined else ""
    return blocks, comments
