"""The PageIndex generation-publication documentation is present and linked."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
PAGE = REPO / "wiki" / "knowledge" / "pageindex-generation-publication.md"


def test_page_has_frontmatter_and_api() -> None:
    text = PAGE.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: ")
    assert "\nsummary: " in text
    for name in (
        "GenerationInfo",
        "StaleGenerationError",
        "TreeLockTimeout",
        "pageindex_get_generation",
        "pageindex_vacuum_tree",
        "generation_grace_s",
    ):
        assert name in text


def test_pageindex_page_links_new_page() -> None:
    text = (REPO / "wiki" / "knowledge" / "pageindex.md").read_text(encoding="utf-8")
    assert "pageindex-generation-publication.md" in text
