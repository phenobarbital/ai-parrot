"""Unit tests for ToolManager.rank_tools() and the search_tools() wrapper
(TASK-2285 — FEAT-434 Claude Agent Tool Bridge).

Tests: rank_tools() ordering by relevance, limit, search_tools exclusion,
deterministic tie-break, missing-description handling, and search_tools()
backward compatibility (JSON string shape + verbatim no-match message).

Run with:
    pytest packages/ai-parrot/tests/test_toolmanager_ranker.py -v
"""
from __future__ import annotations

import json

import pytest
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager

# ── Stubs ──────────────────────────────────────────────────────────────────────


class _WeatherTool(AbstractTool):
    """A tool clearly about weather."""

    name = "get_weather"
    description = "Get the current weather forecast for a location."

    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, status="success", result="sunny")


class _JiraTool(AbstractTool):
    """A tool clearly about Jira ticketing."""

    name = "file_jira_ticket"
    description = "File a new ticket in the Jira issue tracker."

    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, status="success", result="TICKET-1")


class _DatabaseTool(AbstractTool):
    """A tool clearly about database queries."""

    name = "run_database_query"
    description = "Execute a SQL query against the warehouse database."

    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, status="success", result=[])


class _NoDescriptionTool(AbstractTool):
    """A tool with description explicitly set to None."""

    name = "mystery_tool"
    description = None

    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, status="success", result=None)


class _AlphaFirstTool(AbstractTool):
    """Alphabetically first but lexically irrelevant to the tie-break query."""

    name = "aaa_unrelated"
    description = "Completely unrelated tool."

    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, status="success", result=None)


class _ZzzUnrelatedTool(AbstractTool):
    """Alphabetically last, also irrelevant — same score as _AlphaFirstTool."""

    name = "zzz_unrelated"
    description = "Also completely unrelated tool."

    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, status="success", result=None)


@pytest.fixture
def manager() -> ToolManager:
    """A ToolManager with a handful of registered tools spanning topics."""
    tm = ToolManager()
    tm.register_tool(_WeatherTool())
    tm.register_tool(_JiraTool())
    tm.register_tool(_DatabaseTool())
    return tm


# ── rank_tools() ─────────────────────────────────────────────────────────────


class TestRankTools:
    def test_orders_by_relevance_not_alphabetically(self, manager: ToolManager):
        ranked = manager.rank_tools("jira ticket", limit=15)
        names = [tool.name for _score, tool in ranked]
        # "file_jira_ticket" scores highest for this query even though it is
        # not alphabetically first among the three registered tools.
        assert names[0] == "file_jira_ticket"
        assert names.index("file_jira_ticket") < names.index("get_weather")
        assert names.index("file_jira_ticket") < names.index("run_database_query")

    def test_respects_limit(self, manager: ToolManager):
        ranked = manager.rank_tools("tool", limit=2)
        assert len(ranked) == 2

    def test_excludes_search_tools_itself(self, manager: ToolManager):
        manager.register_tool(
            type(
                "_SearchToolsStub",
                (AbstractTool,),
                {
                    "name": "search_tools",
                    "description": "Search for tools.",
                    "_execute": lambda self, **kw: None,
                },
            )()
        )
        ranked = manager.rank_tools("search", limit=15)
        names = [tool.name for _score, tool in ranked]
        assert "search_tools" not in names

    def test_deterministic_tie_break(self):
        tm = ToolManager()
        tm.register_tool(_ZzzUnrelatedTool())
        tm.register_tool(_AlphaFirstTool())
        # Both tools score 0 against this query — tie-break must be by name.
        ranked = tm.rank_tools("nothing-matches-either", limit=15)
        names = [tool.name for _score, tool in ranked]
        assert names == ["aaa_unrelated", "zzz_unrelated"]

    def test_handles_tool_without_description_attribute(self):
        tm = ToolManager()
        tm.register_tool(_NoDescriptionTool())
        # Must not raise even though description is None.
        ranked = tm.rank_tools("mystery", limit=15)
        names = [tool.name for _score, tool in ranked]
        assert "mystery_tool" in names


# ── search_tools() compatibility ─────────────────────────────────────────────


class TestSearchToolsCompat:
    def test_still_returns_json_string(self, manager: ToolManager):
        out = manager.search_tools("weather")
        assert isinstance(out, str)
        parsed = json.loads(out)
        assert isinstance(parsed, list)

    def test_keys_are_name_and_description(self, manager: ToolManager):
        out = manager.search_tools("weather")
        parsed = json.loads(out)
        assert parsed
        for entry in parsed:
            assert set(entry.keys()) == {"name", "description"}

    def test_no_match_message_verbatim(self, manager: ToolManager):
        out = manager.search_tools("zzzz-nothing")
        assert out == "No tools found matching 'zzzz-nothing'. Try a different search term."

    def test_matching_tool_is_found(self, manager: ToolManager):
        out = manager.search_tools("jira")
        parsed = json.loads(out)
        names = [entry["name"] for entry in parsed]
        assert "file_jira_ticket" in names

    def test_delegates_to_rank_tools(self, manager: ToolManager, monkeypatch):
        calls = []
        original = manager.rank_tools

        def _spy(query, limit=15):
            calls.append((query, limit))
            return original(query, limit)

        monkeypatch.setattr(manager, "rank_tools", _spy)
        manager.search_tools("weather", limit=5)
        assert calls == [("weather", 5)]

    def test_blank_query_matches_every_registered_tool(self, manager: ToolManager):
        # Regression (code review, FEAT-434): the legacy substring check
        # (`"" in name.lower()`) always matched, so search_tools("") browsed
        # the full registry. The lexical scorer must preserve that — an
        # empty query must not score every tool 0 and collapse to the
        # no-match message.
        out = manager.search_tools("")
        parsed = json.loads(out)
        names = {entry["name"] for entry in parsed}
        assert names == {"get_weather", "file_jira_ticket", "run_database_query"}

    def test_whitespace_only_query_matches_every_registered_tool(self, manager: ToolManager):
        out = manager.search_tools("   ")
        parsed = json.loads(out)
        names = {entry["name"] for entry in parsed}
        assert names == {"get_weather", "file_jira_ticket", "run_database_query"}
