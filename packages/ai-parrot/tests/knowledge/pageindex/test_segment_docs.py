"""The PageIndex segment-store documentation is present and linked."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
PAGE = REPO / "wiki" / "knowledge" / "pageindex-segment-store.md"


def test_page_has_frontmatter_and_api() -> None:
    text = PAGE.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: ")
    assert "\nsummary: " in text
    for name in (
        "DocumentRevision", "SegmentStore", "pageindex_read_pages", "pageindex_read_segments",
        "pageindex_outline", "pageindex_index_segments", "get_injection_scoring_engine",
        "frame_segments", "bookstore_read_pages", "read_max_chars",
    ):
        assert name in text


def test_pageindex_page_links_new_page() -> None:
    text = (REPO / "wiki" / "knowledge" / "pageindex.md").read_text(encoding="utf-8")
    assert "pageindex-segment-store.md" in text


def test_generation_page_mentions_revisions() -> None:
    text = (REPO / "wiki" / "knowledge" / "pageindex-generation-publication.md").read_text(encoding="utf-8")
    assert "segments/" in text and "revision" in text
