"""FEAT-803 AC3/AC11: chapter overviews are concept intros with wiki links."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHAPTERS = ["foundations", "llm-clients", "bots-agents"]
WIKI = re.compile(r"https://github\.com/phenobarbital/ai-parrot/wiki/[A-Za-z0-9._-]+")


@pytest.mark.parametrize("name", CHAPTERS)
def test_chapter_follows_pattern(name: str) -> None:
    text = (ROOT / "docs" / "chapters" / f"{name}.md").read_text(encoding="utf-8")
    for heading in ("## Key Concepts", "## What You Can Build", "## Deep Dive"):
        assert heading in text
    assert WIKI.search(text)
    words = len(text.split())
    assert 250 <= words <= 650, words
    # AC11 — no reference duplication: assert no ```python fenced blocks longer than 15 lines
    python_blocks = re.findall(r"```python\n(.*?)```", text, re.DOTALL)
    for block in python_blocks:
        lines = block.strip().split("\n")
        assert len(lines) <= 15, f"Found Python block with {len(lines)} lines in {name}.md"
