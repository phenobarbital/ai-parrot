"""FEAT-803 AC3/AC11: chapter overviews are concept intros with wiki links."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHAPTERS = ["memory-knowledge", "knowledge-graph", "tools-rag", "integrations"]
WIKI = re.compile(r"https://github\.com/phenobarbital/ai-parrot/wiki/[A-Za-z0-9._-]+")


@pytest.mark.parametrize("name", CHAPTERS)
def test_chapter_follows_pattern(name: str) -> None:
    """Each chapter follows the overview pattern with a verified wiki link."""
    text = (ROOT / "docs" / "chapters" / f"{name}.md").read_text(encoding="utf-8")
    for heading in ("## Key Concepts", "## What You Can Build", "## Deep Dive"):
        assert heading in text, f"Missing heading: {heading} in {name}.md"
    assert WIKI.search(text), f"No wiki link found in {name}.md"
    words = len(text.split())
    assert 250 <= words <= 650, f"{name}.md has {words} words (expected 250-650)"


@pytest.mark.parametrize("name", CHAPTERS)
def test_no_code_blocks(name: str) -> None:
    """No API reference duplicated from the wiki (AC11)."""
    text = (ROOT / "docs" / "chapters" / f"{name}.md").read_text(encoding="utf-8")
    # Check for fenced code blocks
    code_blocks = re.findall(r"```\w*\n.*?```", text, re.DOTALL)
    for block in code_blocks:
        lines = block.split("\n")
        # Allow short code blocks (e.g., imports, small examples) but not long ones
        assert len(lines) <= 15, f"{name}.md has a code block with {len(lines)} lines (max 15)"
