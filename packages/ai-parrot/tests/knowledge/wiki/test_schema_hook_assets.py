from pathlib import Path

from parrot.knowledge.wiki.claude_code import assets


def test_ingest_line_inside_guard(tmp_path: Path) -> None:
    """The schema ingest command is protected by the linked-worktree guard."""
    block = assets.git_hook_block(tmp_path)
    guard_start = block.index("if [ ! -f .git ]; then")
    ingest = block.index("schema ingest-ddl --changed --quiet")
    guard_end = block.index("\nfi\n")

    assert guard_start < ingest < guard_end


def test_permissions_present() -> None:
    """All schema-plane MCP tools are included in the permission allowlist."""
    text = Path(assets.__file__).read_text(encoding="utf-8")

    for name in ("lookup", "search", "neighbors", "sources"):
        assert f"mcp__wikitoolkit__wiki_schema_{name}" in text
