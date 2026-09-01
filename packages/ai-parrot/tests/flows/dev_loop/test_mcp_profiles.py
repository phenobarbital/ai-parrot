"""Unit tests for the shared MCP dispatch-profile helpers.

Covers ``parrot.flows.dev_loop.mcp_profiles`` — the module the research
seats (``ResearchNode`` / ``IdeationNode``) share for wikitoolkit MCP
wiring and allow-rule derivation.
"""

from __future__ import annotations

from pathlib import Path

from parrot.flows.dev_loop.mcp_profiles import (
    WIKI_MCP_TOOLS,
    derive_mcp_tool_names,
    resolve_wikitoolkit_command,
    wikitoolkit_mcp_entry,
)


class TestWikiMcpTools:
    def test_readonly_trio_frozen(self):
        """GUARD: exactly the three read-only tools — never the write ones."""
        assert WIKI_MCP_TOOLS == (
            "mcp__wikitoolkit__wiki_query",
            "mcp__wikitoolkit__wiki_page",
            "mcp__wikitoolkit__wiki_related",
        )

    def test_ideation_aliases_are_the_same_objects(self):
        """The pre-move private names on ideation.py stay identical."""
        from parrot.flows.dev_flow.nodes import ideation

        assert ideation._WIKI_MCP_TOOLS is WIKI_MCP_TOOLS
        assert ideation._resolve_wikitoolkit_command is resolve_wikitoolkit_command


class TestResolveWikitoolkitCommand:
    def test_path_hit_wins(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _name: "/opt/bin/wikitoolkit")
        assert resolve_wikitoolkit_command() == "/opt/bin/wikitoolkit"

    def test_sys_executable_sibling_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setattr("shutil.which", lambda _name: None)
        candidate = tmp_path / "wikitoolkit"
        candidate.write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.setattr("sys.executable", str(tmp_path / "python"))
        assert resolve_wikitoolkit_command() == str(candidate)

    def test_bare_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setattr("shutil.which", lambda _name: None)
        monkeypatch.setattr("sys.executable", str(tmp_path / "python"))
        assert resolve_wikitoolkit_command() == "wikitoolkit"


class TestWikitoolkitMcpEntry:
    def test_shape(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _name: "/opt/bin/wikitoolkit")
        assert wikitoolkit_mcp_entry() == {
            "command": "/opt/bin/wikitoolkit",
            "args": ["mcp"],
            "env": {},
        }


class TestDeriveMcpToolNames:
    def test_one_server_level_rule_per_server_sorted(self):
        servers = {"parrot-repo": {}, "wikitoolkit": {}, "parrot-memory": {}}
        assert derive_mcp_tool_names(servers) == [
            "mcp__parrot-memory",
            "mcp__parrot-repo",
            "mcp__wikitoolkit",
        ]

    def test_empty_mapping(self):
        assert derive_mcp_tool_names({}) == []
