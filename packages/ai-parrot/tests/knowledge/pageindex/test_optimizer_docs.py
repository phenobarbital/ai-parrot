"""The PageIndex tree-optimizer documentation is present and linked (FEAT-846)."""

from pathlib import Path

from parrot.knowledge.pageindex.optimizer import OptimizerSettings

REPO = Path(__file__).resolve().parents[5]
WIKI = REPO / "wiki" / "knowledge"
PAGE = WIKI / "pageindex-tree-optimizer.md"


def test_optimizer_page_exists_and_names_settings_and_commands() -> None:
    text = PAGE.read_text(encoding="utf-8")
    assert text.startswith("---\ntitle: ")
    assert "\nsummary: " in text
    for field in OptimizerSettings.model_fields:
        assert f"`{field}`" in text, field
    for name in (
        "parrot pageindex optimize",
        "bookstore optimize",
        "optimize_on_import",
        "optimizer_settings",
        "key_items",
        "aliases",
        "optimizer_eval",
        "tuned_target",
        "DATA_FRAMING_INSTRUCTION",
        "pageindex_optimize",
        "issue:7111d74a3066",
        "issue:336eef8010a1",
    ):
        assert name in text, name


def test_optimizer_page_documents_feat_853_fixes() -> None:
    """The optimizer page names the FEAT-853 behaviour: bounded prompts, re-homed anchors, pseudo-headings."""
    text = PAGE.read_text(encoding="utf-8")
    for name in (
        "LLM_INPUT_BUDGET_TOKENS",
        "running_key",
        "start_index",
        "end_index",
        "window_reads",
        "key_items_rehomed",
        "reconcile_key_items",
        "is_heading_text",
        "pseudo_heading_segments",
        "PSEUDO_HEADING_MAX_REPEATS",
        "document_running_keys",
        "RUNNING_LINE_MIN_DENSITY",
        "table_page_splits",
        "TABLE_SPLIT_MIN_SHARE",
    ):
        assert name in text, name


def test_pages_link_optimizer_page() -> None:
    pageindex = (WIKI / "pageindex.md").read_text(encoding="utf-8")
    assert "pageindex-tree-optimizer.md" in pageindex
    assert "optimize_on_import" in pageindex
    assert "optimizer_settings" in pageindex
    local_mcp = (WIKI / "pageindex-local-mcp.md").read_text(encoding="utf-8")
    assert "pageindex_optimize" in local_mcp
    assert "pageindex-tree-optimizer.md" in local_mcp
