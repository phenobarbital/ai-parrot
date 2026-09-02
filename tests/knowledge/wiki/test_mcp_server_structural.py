"""FEAT-498 TASK-2750 — MCP registration of the structural-plane tools."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server


@pytest.fixture
def built_project_root(tmp_path: Path) -> Path:
    """A built wiki project with a caller and a callee."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (root / "b.py").write_text(
        "from a import helper\n\n\ndef run():\n    return helper()\n", encoding="utf-8"
    )
    result = CliRunner().invoke(wiki, ["build", "--path", str(root), "--no-git", "-q"])
    assert result.exit_code == 0, result.output
    return root


class TestMCPServerStructuralRegistration:
    def test_registers_nine_tools(self, built_project_root: Path):
        server = create_wiki_mcp_server(built_project_root)
        names = set(server.tools.keys())
        assert {"wiki_symbol_lookup", "wiki_code_outline", "wiki_blast_radius"} <= names
        assert len(names) == 9

    @pytest.mark.asyncio
    async def test_symbol_lookup_over_stdio_tool(self, built_project_root: Path):
        server = create_wiki_mcp_server(built_project_root)
        adapter = server.tools["wiki_symbol_lookup"]
        result = await adapter.tool._execute(query="helper")
        assert result.result["total"] >= 1

    def test_stub_line_style_tool_docstrings_present(self, built_project_root: Path):
        server = create_wiki_mcp_server(built_project_root)
        for name in ("wiki_symbol_lookup", "wiki_code_outline", "wiki_blast_radius"):
            assert server.tools[name].tool.description
