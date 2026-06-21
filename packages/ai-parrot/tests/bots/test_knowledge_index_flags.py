"""Tests for the knowledge-index capability flags on bots.

Exercises the PageIndex / GraphIndex capability surface that
:class:`parrot.interfaces.tools.ToolInterface` contributes to every bot:
``pageindex_toolkit`` / ``graphindex_toolkit`` accessors and the
``has_pageindex_tools`` / ``has_graphindex_tools`` flags used by the REST
``AgentKnowledgeHandler``.

A lightweight harness mixes ``ToolInterface`` with a real ``ToolManager`` so the
flag logic is tested directly, without standing up the full ``BasicAgent``
stack (LLM client, MCP, vector store, ...).
"""
from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.interfaces.tools import ToolInterface
from parrot.knowledge.pageindex.ingest import IngestedMarkdown
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
from parrot.tools.manager import ToolManager


class _Harness(ToolInterface):
    """Minimal bot-like object exposing the tool-management surface."""

    def __init__(self) -> None:
        self.logger = logging.getLogger("test.harness")
        self.tool_manager = ToolManager(logger=self.logger)
        self.enable_tools = True
        self._pageindex_toolkit = None
        self._graphindex_toolkit = None
        self._graphindex_builder = None


def _adapter() -> MagicMock:
    a = MagicMock()
    a.model = "heavy"
    a.client = MagicMock()
    a.client.ask = AsyncMock(return_value=MagicMock(output="x", structured_output=None))
    a.client.default_model = "test-model"
    a.ask = AsyncMock(return_value="cot")
    a.ask_structured = AsyncMock(
        return_value=IngestedMarkdown(title="t", summary="s", markdown="# t\n\nbody")
    )
    return a


@pytest.fixture
def pageindex_toolkit(tmp_path: Path) -> PageIndexToolkit:
    return PageIndexToolkit(adapter=_adapter(), storage_dir=tmp_path, lightweight_model="light")


def test_bare_bot_reports_no_knowledge_index():
    bot = _Harness()
    assert bot.has_pageindex_tools is False
    assert bot.has_graphindex_tools is False
    assert bot.has_knowledge_index is False
    assert bot.pageindex_toolkit is None
    assert bot.graphindex_toolkit is None


def test_pageindex_toolkit_is_captured_and_flagged(pageindex_toolkit: PageIndexToolkit):
    bot = _Harness()
    bot._initialize_tools([pageindex_toolkit])

    # Tools were registered into the manager...
    assert any(n.startswith("pageindex") for n in bot.tool_manager.list_tools())
    # ...and the toolkit instance was captured for the REST handler.
    assert bot.pageindex_toolkit is pageindex_toolkit
    assert bot.has_pageindex_tools is True
    assert bot.has_knowledge_index is True
    # GraphIndex remains absent.
    assert bot.has_graphindex_tools is False


def test_has_pageindex_tools_falls_back_to_tool_prefix():
    """Even without instance capture, a pageindex-prefixed tool flags True."""
    bot = _Harness()
    bot.tool_manager.register_tool(
        name="pageindex_search",
        description="search",
        input_schema={"type": "object", "properties": {}},
        function=lambda **_: None,
    )
    assert bot.pageindex_toolkit is None
    assert bot.has_pageindex_tools is True


def test_graphindex_builder_accessor_defaults_none():
    bot = _Harness()
    assert bot.graphindex_builder is None
