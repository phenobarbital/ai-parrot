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


def test_pages_link_optimizer_page() -> None:
    pageindex = (WIKI / "pageindex.md").read_text(encoding="utf-8")
    assert "pageindex-tree-optimizer.md" in pageindex
    assert "optimize_on_import" in pageindex
    assert "optimizer_settings" in pageindex
    local_mcp = (WIKI / "pageindex-local-mcp.md").read_text(encoding="utf-8")
    assert "pageindex_optimize" in local_mcp
    assert "pageindex-tree-optimizer.md" in local_mcp
