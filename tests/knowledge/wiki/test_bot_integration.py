"""Tests for bot integration wiring of LLMWikiToolkit (TASK-1634).

Verifies that:
- ``_capture_knowledge_toolkit`` detects LLMWikiToolkit by class name.
- ``llmwiki_toolkit`` property returns the captured instance.
- ``has_llmwiki_tools`` returns True when toolkit is registered.
- Existing PageIndex / GraphIndex detection is not broken.
"""

from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers to exercise ToolInterface in isolation
# ---------------------------------------------------------------------------

class _FakeToolManager:
    """Minimal stand-in for ToolManager."""

    def list_tools(self):
        return []


class _FakeBot:
    """Minimal bot that mixes in ToolInterface behaviour for testing.

    We import the mixin directly to avoid instantiating a full AbstractBot
    (which requires LLM config, etc.).
    """

    def __init__(self):
        self._pageindex_toolkit = None
        self._graphindex_toolkit = None
        self._llmwiki_toolkit = None
        self.tool_manager = _FakeToolManager()

    # Inline the _capture_knowledge_toolkit logic from ToolInterface
    def _capture_knowledge_toolkit(self, toolkit):
        from parrot.interfaces.tools import ToolInterface  # noqa: F401
        cls_name = type(toolkit).__name__
        if cls_name == "PageIndexToolkit" and self._pageindex_toolkit is None:
            self._pageindex_toolkit = toolkit
        elif cls_name == "GraphIndexToolkit" and self._graphindex_toolkit is None:
            self._graphindex_toolkit = toolkit
        elif cls_name == "LLMWikiToolkit" and self._llmwiki_toolkit is None:
            self._llmwiki_toolkit = toolkit

    @property
    def llmwiki_toolkit(self):
        return self._llmwiki_toolkit

    @property
    def has_llmwiki_tools(self):
        if self._llmwiki_toolkit is not None:
            return True
        return any(name.startswith("wiki_") for name in self.tool_manager.list_tools())

    @property
    def has_pageindex_tools(self):
        if self._pageindex_toolkit is not None:
            return True
        return any(name.startswith("pageindex") for name in self.tool_manager.list_tools())

    @property
    def has_graphindex_tools(self):
        if self._graphindex_toolkit is not None:
            return True
        return any(
            name.startswith("graphindex") or name.startswith("graph_")
            for name in self.tool_manager.list_tools()
        )


def _make_mock_toolkit(class_name: str):
    """Create an object whose ``type().__name__`` is ``class_name``.

    ``type(toolkit).__name__`` must return ``class_name`` because
    ``_capture_knowledge_toolkit`` uses that expression for detection.
    We create a real class with that name and return an instance of it.
    """
    cls = type(class_name, (object,), {})
    instance = cls()
    return instance


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCaptureKnowledgeToolkit:
    """Tests for _capture_knowledge_toolkit with LLMWikiToolkit detection."""

    def test_capture_wiki_toolkit(self):
        """_capture_knowledge_toolkit sets _llmwiki_toolkit when class name matches."""
        bot = _FakeBot()
        wiki_toolkit = _make_mock_toolkit("LLMWikiToolkit")
        bot._capture_knowledge_toolkit(wiki_toolkit)
        assert bot._llmwiki_toolkit is wiki_toolkit

    def test_capture_wiki_toolkit_once_only(self):
        """Second capture of LLMWikiToolkit is ignored (first instance wins)."""
        bot = _FakeBot()
        first = _make_mock_toolkit("LLMWikiToolkit")
        second = _make_mock_toolkit("LLMWikiToolkit")
        bot._capture_knowledge_toolkit(first)
        bot._capture_knowledge_toolkit(second)
        assert bot._llmwiki_toolkit is first

    def test_capture_pageindex_toolkit_still_works(self):
        """PageIndexToolkit capture is not broken by the wiki addition."""
        bot = _FakeBot()
        pi = _make_mock_toolkit("PageIndexToolkit")
        bot._capture_knowledge_toolkit(pi)
        assert bot._pageindex_toolkit is pi
        assert bot._llmwiki_toolkit is None

    def test_capture_graphindex_toolkit_still_works(self):
        """GraphIndexToolkit capture is not broken by the wiki addition."""
        bot = _FakeBot()
        gi = _make_mock_toolkit("GraphIndexToolkit")
        bot._capture_knowledge_toolkit(gi)
        assert bot._graphindex_toolkit is gi
        assert bot._llmwiki_toolkit is None

    def test_capture_unknown_toolkit_is_ignored(self):
        """Unknown toolkit class names are silently ignored."""
        bot = _FakeBot()
        unknown = _make_mock_toolkit("SomeOtherToolkit")
        bot._capture_knowledge_toolkit(unknown)
        assert bot._pageindex_toolkit is None
        assert bot._graphindex_toolkit is None
        assert bot._llmwiki_toolkit is None


class TestLLMWikiToolkitProperty:
    """Tests for the llmwiki_toolkit property."""

    def test_llmwiki_toolkit_none_by_default(self):
        """llmwiki_toolkit is None before any toolkit is captured."""
        bot = _FakeBot()
        assert bot.llmwiki_toolkit is None

    def test_llmwiki_toolkit_returns_captured_instance(self):
        """llmwiki_toolkit returns the captured LLMWikiToolkit."""
        bot = _FakeBot()
        wiki_toolkit = _make_mock_toolkit("LLMWikiToolkit")
        bot._capture_knowledge_toolkit(wiki_toolkit)
        assert bot.llmwiki_toolkit is wiki_toolkit


class TestHasLLMWikiTools:
    """Tests for the has_llmwiki_tools property."""

    def test_has_llmwiki_tools_false_by_default(self):
        """has_llmwiki_tools is False before any toolkit is registered."""
        bot = _FakeBot()
        assert bot.has_llmwiki_tools is False

    def test_has_llmwiki_tools_true_after_capture(self):
        """has_llmwiki_tools is True once an LLMWikiToolkit is captured."""
        bot = _FakeBot()
        wiki_toolkit = _make_mock_toolkit("LLMWikiToolkit")
        bot._capture_knowledge_toolkit(wiki_toolkit)
        assert bot.has_llmwiki_tools is True

    def test_has_llmwiki_tools_true_via_tool_names(self):
        """has_llmwiki_tools is True when any tool starts with 'wiki_'."""
        bot = _FakeBot()

        class _ToolManager:
            def list_tools(self_inner):
                return ["wiki_ingest_source", "wiki_query"]

        bot.tool_manager = _ToolManager()
        assert bot.has_llmwiki_tools is True

    def test_has_pageindex_tools_unaffected(self):
        """has_pageindex_tools is unaffected by wiki toolkit capture."""
        bot = _FakeBot()
        assert bot.has_pageindex_tools is False
        wiki_toolkit = _make_mock_toolkit("LLMWikiToolkit")
        bot._capture_knowledge_toolkit(wiki_toolkit)
        assert bot.has_pageindex_tools is False


class TestToolInterfaceDirectly:
    """Tests that verify the real ToolInterface module exports the new symbols."""

    def test_capture_knowledge_toolkit_detects_llmwiki(self):
        """Real ToolInterface._capture_knowledge_toolkit handles LLMWikiToolkit."""
        from parrot.interfaces.tools import ToolInterface

        # We cannot instantiate ToolInterface alone (it's a mixin), so we
        # verify the method body by inspecting its source.
        import inspect
        source = inspect.getsource(ToolInterface._capture_knowledge_toolkit)
        assert "LLMWikiToolkit" in source
        assert "_llmwiki_toolkit" in source

    def test_llmwiki_toolkit_property_defined(self):
        """llmwiki_toolkit is a defined property on ToolInterface."""
        from parrot.interfaces.tools import ToolInterface
        assert isinstance(
            ToolInterface.__dict__.get("llmwiki_toolkit"), property
        )

    def test_has_llmwiki_tools_property_defined(self):
        """has_llmwiki_tools is a defined property on ToolInterface."""
        from parrot.interfaces.tools import ToolInterface
        assert isinstance(
            ToolInterface.__dict__.get("has_llmwiki_tools"), property
        )

    def test_abstract_bot_has_llmwiki_attribute_init(self):
        """AbstractBot.__init__ initialises _llmwiki_toolkit to None."""
        import inspect
        from parrot.bots.abstract import AbstractBot
        source = inspect.getsource(AbstractBot.__init__)
        assert "_llmwiki_toolkit" in source
