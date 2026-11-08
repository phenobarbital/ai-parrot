"""The PageIndex agentic-retrieval documentation is present and linked."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
PAGE = REPO / "wiki" / "knowledge" / "pageindex-agentic-retrieval.md"


def test_page_has_frontmatter_api_and_reasons() -> None:
    text = PAGE.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: ")
    assert "\nsummary: " in text
    for name in (
        "ReadLedger",
        "validate_citations",
        "EvidenceBundle",
        "agentic_retrieve",
        "clone_for_tools",
        "bad_address",
        "revision_unread",
        "revision_unavailable",
        "segment_unread",
        "empty_excerpt",
        "excerpt_not_found",
        "outside_covered_ranges",
        "no_tool_calls",
        "max_tool_calls",
        "parse_error",
    ):
        assert name in text


def test_related_pages_link_new_page() -> None:
    for page in ("pageindex.md", "pageindex-segment-store.md", "pageindex-local-mcp.md"):
        text = (REPO / "wiki" / "knowledge" / page).read_text(encoding="utf-8")
        assert "pageindex-agentic-retrieval.md" in text


def test_local_mcp_exclude_slot_names_the_agentic_tool() -> None:
    text = (REPO / "wiki" / "knowledge" / "pageindex-local-mcp.md").read_text(encoding="utf-8")
    assert "exclude: [pageindex_agentic_retrieve]" in text
    assert "`exclude:` in the template is the agreed place" in text
