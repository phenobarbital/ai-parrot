"""Tests for ``ToolManager.load_tool`` name resolution.

``load_tool`` must resolve individual ``parrot_tools`` tools by their
canonical ``TOOL_REGISTRY`` name (e.g. ``ibisworld``, ``yfinance``,
``web_scraping_tool``). Historically it only knew the legacy
``parrot.tools.<name>`` import path and could not load these tools at all,
which surfaced as ``Unknown tool or toolkit`` warnings for bots that listed
them.
"""
import pytest

pytest.importorskip("parrot_tools")

from parrot.tools.manager import ToolManager


class TestLoadToolFromRegistry:
    """Individual parrot_tools tools resolve by their canonical name."""

    @pytest.mark.parametrize(
        "name",
        ["ibisworld", "yfinance", "web_scraping_tool"],
    )
    def test_individual_tool_resolves(self, name):
        tm = ToolManager()
        assert tm.load_tool(name) is True
        assert tm.tool_count() > 0

    def test_resolution_is_case_insensitive(self):
        tm = ToolManager()
        assert tm.load_tool("YFinance") is True

    def test_toolkit_name_resolves_and_expands(self):
        tm = ToolManager()
        assert tm.load_tool("web_scraping") is True
        # A toolkit registers more than one tool.
        assert tm.tool_count() >= 1

    def test_already_registered_is_noop_success(self):
        tm = ToolManager()
        assert tm.load_tool("ibisworld") is True
        count = tm.tool_count()
        # Loading again must not error nor duplicate.
        assert tm.load_tool("ibisworld") is True
        assert tm.tool_count() == count

    def test_unknown_name_returns_false(self):
        tm = ToolManager()
        # Legacy/incorrect names that are neither registry keys nor
        # importable parrot.tools.<name> modules must fail cleanly.
        assert tm.load_tool("DefinitelyNotATool") is False
