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
        "provider_error",
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


def test_page_documents_cap_fill_lock_and_reuse() -> None:
    """The page states the termination, concurrency and re-import semantics (FEAT-849 FR-5)."""
    text = PAGE.read_text(encoding="utf-8")
    for phrase in (
        "Cap-fill ends the loop immediately",
        "provider-done / stop tie",
        "One agentic request at a time per toolkit",
        "byte-identical re-import is a no-op",
        "reused: true",
    ):
        assert phrase in text, phrase


def test_page_does_not_claim_every_exception_propagates() -> None:
    """The provider-failure path is returned, not raised, so the old blanket claim must be gone."""
    text = PAGE.read_text(encoding="utf-8")
    assert "Exceptions still propagate:" not in text
    assert "Some exceptions still propagate" in text

