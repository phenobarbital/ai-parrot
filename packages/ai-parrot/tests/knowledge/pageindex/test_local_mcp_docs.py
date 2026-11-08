"""The PageIndex local-MCP documentation is present and linked (FEAT-842)."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
PAGE = REPO / "wiki" / "knowledge" / "pageindex-local-mcp.md"


def test_page_has_frontmatter_and_names() -> None:
    text = PAGE.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: ")
    assert "\nsummary: " in text
    for name in (
        "parrot toolkits install pageindex",
        "storage_dir",
        "max_result_chars",
        "llm_client",
        "pageindex_insert_content",
        "pageindex_import_file",
        "pageindex_import_folder",
        "pageindex_import_pdf",
        "pageindex_search_documents_scoped",
        "exclude",
    ):
        assert name in text


def test_pages_link_new_page() -> None:
    pageindex = (REPO / "wiki" / "knowledge" / "pageindex.md").read_text(encoding="utf-8")
    assert "pageindex-local-mcp.md" in pageindex
    toolkits = (REPO / "wiki" / "tools" / "mcp-local-toolkits.md").read_text(encoding="utf-8")
    assert "## `pageindex`" in toolkits
    assert "pageindex-local-mcp.md" in toolkits
    assert toolkits.index("## `pageindex`") < toolkits.index("## `sdd-coder`")
