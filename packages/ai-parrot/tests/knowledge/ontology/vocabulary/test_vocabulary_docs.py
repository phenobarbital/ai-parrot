"""The FEAT-824 documentation pages exist and follow the techwiki template."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[6]
PAGES = ["wiki/knowledge/ontology-backend-programme.md", "wiki/knowledge/ontology-vocabulary-store.md"]
SECTIONS = [
    "## Purpose",
    "## Public API",
    "## Configuration & Parameters",
    "## Usage Examples",
    "## Gotchas",
    "## Related",
]


@pytest.mark.parametrize("page", PAGES)
def test_page_follows_template(page: str) -> None:
    text = (ROOT / page).read_text(encoding="utf-8")
    assert text.startswith("---\n") and "\ntitle:" in text and "\nsummary:" in text
    for section in SECTIONS:
        assert section in text, (page, section)
    assert "FILL IN" not in text
