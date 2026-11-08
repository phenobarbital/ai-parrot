"""The PageIndex layout-structure documentation is present and linked (FEAT-845)."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
WIKI = REPO / "wiki" / "knowledge"
PAGE = WIKI / "pageindex-layout-structure.md"


def test_page_has_frontmatter_and_names() -> None:
    text = PAGE.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: ")
    assert "\nsummary: " in text
    for name in (
        "structure_mode",
        "structure_source",
        "structure_min_confidence",
        "hybrid",
        "bookmarks",
        "PDFStructureError",
        "NoTextLayerError",
        "UnreadablePDFError",
        "DATA_FRAMING_INSTRUCTION",
        "layout_eval",
    ):
        assert name in text


def test_pages_link_new_page() -> None:
    pageindex = (WIKI / "pageindex.md").read_text(encoding="utf-8")
    assert "pageindex-layout-structure.md" in pageindex
    assert "structure_mode" in pageindex
    codex = (WIKI / "bookstore-codex.md").read_text(encoding="utf-8")
    assert "pageindex-layout-structure.md" in codex
    assert "PDFs can be added without an LLM" in codex
