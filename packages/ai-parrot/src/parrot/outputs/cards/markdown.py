# packages/ai-parrot/src/parrot/outputs/cards/markdown.py
"""Markdown text → list[CardSection] parser."""
from __future__ import annotations

import re

from .sections import (
    CardSection,
    CodeSection,
    ImageSection,
    ImageEntry,
    TableSection,
    TextSection,
)

_IMAGE_RE = re.compile(r'^!\[([^\]]*)\]\(([^)]+)\)\s*$')
_FENCE_OPEN_RE = re.compile(r'^```(\w*)\s*$')
_FENCE_CLOSE_RE = re.compile(r'^```\s*$')
_TABLE_ROW_RE = re.compile(r'^\|(.+)\|\s*$')
_TABLE_SEP_RE = re.compile(r'^[\s|:-]+$')


def markdown_to_sections(text: str) -> list[CardSection]:
    """Parse markdown text into a list of CardSection instances.

    Splits on structural boundaries (fenced code blocks, pipe tables,
    standalone images) and groups everything else into TextSection
    blocks, leaving inline markdown (bold, italic, links) intact.

    Args:
        text: Raw markdown text to parse.

    Returns:
        A list of CardSection instances (TextSection, TableSection,
        CodeSection, ImageSection) in document order. Empty list if
        `text` is empty or whitespace-only.
    """
    if not text or not text.strip():
        return []

    lines = text.split('\n')
    sections: list[CardSection] = []
    current_text: list[str] = []
    i = 0

    def flush_text():
        if current_text:
            joined = '\n'.join(current_text).strip()
            if joined:
                sections.append(TextSection(text=joined))
            current_text.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Fenced code block
        fence_match = _FENCE_OPEN_RE.match(stripped)
        if fence_match and not stripped.endswith('```'):
            flush_text()
            language = fence_match.group(1) or None
            code_lines: list[str] = []
            i += 1
            while i < len(lines):
                if _FENCE_CLOSE_RE.match(lines[i].strip()):
                    break
                code_lines.append(lines[i])
                i += 1
            sections.append(CodeSection(code='\n'.join(code_lines), language=language))
            i += 1
            continue

        # Standalone image
        img_match = _IMAGE_RE.match(stripped)
        if img_match:
            flush_text()
            alt_text = img_match.group(1)
            url = img_match.group(2)
            sections.append(ImageSection(images=[ImageEntry(url=url, alt_text=alt_text)]))
            i += 1
            continue

        # Pipe table
        if _TABLE_ROW_RE.match(stripped):
            # Look ahead for separator row
            if (i + 1 < len(lines)
                    and _TABLE_ROW_RE.match(lines[i + 1].strip())
                    and _TABLE_SEP_RE.match(
                        lines[i + 1].strip().strip('|').replace(' ', ''))):
                flush_text()
                header_line = stripped[1:-1]
                headers = [h.strip() for h in header_line.split('|')]
                i += 2  # skip header + separator
                rows: list[list[str]] = []
                while i < len(lines) and _TABLE_ROW_RE.match(lines[i].strip()):
                    row_line = lines[i].strip()[1:-1]
                    vals = [v.strip() for v in row_line.split('|')]
                    rows.append(vals[:len(headers)])
                    i += 1
                sections.append(TableSection(columns=headers, rows=rows))
                continue

        current_text.append(line)
        i += 1

    flush_text()
    return sections
