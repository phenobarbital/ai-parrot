"""Test that schema-plane documentation exists and contains required content."""

from pathlib import Path

# Anchored to the repo root via __file__, not the process cwd: importing
# `parrot` triggers a navconfig side-effect that chdirs the process to the
# main checkout's package root, so a bare relative Path("docs/...") silently
# resolves against the wrong repo once pytest has loaded any fixture chain
# that imports parrot.
_REPO_ROOT = Path(__file__).resolve().parents[6]


def test_guide_mentions_verbs_and_tools():
    """Verify that docs/wiki/schema-plane.md exists and documents the six verbs and four tools."""
    text = (_REPO_ROOT / "docs" / "wiki" / "schema-plane.md").read_text()

    # Test for the six CLI verbs (from FEAT-600 spec AC15)
    verbs = ("sources", "add-source", "sync", "ingest-ddl", "diff", "lookup")
    for verb in verbs:
        assert verb in text, f"Schema plane guide must mention verb '{verb}'"

    # Test for the four MCP tools
    tools = (
        "wiki_schema_lookup",
        "wiki_schema_search",
        "wiki_schema_neighbors",
        "wiki_schema_sources",
    )
    for tool in tools:
        assert tool in text, f"Schema plane guide must mention tool '{tool}'"

    # Test for id grammar documentation
    assert "table:<origin>/<schema>.<table>" in text, "Schema plane guide must document id grammar"
