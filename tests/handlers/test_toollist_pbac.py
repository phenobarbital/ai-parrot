"""Unit tests for ToolList PBAC filtering (TASK-713)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _fake_resolver(mapping, host=None):
    """Fake ToolkitResolver exposing ``mapping`` (slug -> dotted path) plus optional host (walk/host) entries."""
    from parrot.tools.resolver import ToolkitEntry

    resolver = MagicMock()
    entries = [ToolkitEntry(slug=k, dotted_path=v, source="parrot_tools") for k, v in mapping.items()]
    entries += [ToolkitEntry(slug=k, dotted_path=v, source=src) for k, (v, src) in (host or {}).items()]
    resolver.entries.return_value = entries
    resolver.resolve.return_value = None
    return resolver


class TestToolListPBAC:
    """Tests for ToolList.get() PBAC filtering."""

    def _make_handler(self, has_pdp: bool = True, allowed_tools=None):
        """Create a ToolList mock with configurable PDP state."""
        from parrot.handlers.bots import ToolList

        handler = MagicMock(spec=ToolList)
        handler.logger = MagicMock()  # instance attr — not on class spec, must be set explicitly

        session = MagicMock()
        session.get = MagicMock(return_value={
            "username": "user", "groups": ["engineering"],
            "roles": [], "programs": [],
        })
        handler.request = MagicMock()
        handler.request.session = session

        if has_pdp:
            mock_result = MagicMock()
            mock_result.allowed = allowed_tools  # None = all allowed, list = filter
            mock_evaluator = MagicMock()
            mock_evaluator.filter_resources = MagicMock(return_value=mock_result)
            mock_pdp = MagicMock()
            mock_pdp._evaluator = mock_evaluator
            handler.request.app.get = MagicMock(return_value=mock_pdp)
        else:
            handler.request.app.get = MagicMock(return_value=None)

        handler._get_pbac_evaluator = ToolList._get_pbac_evaluator.__get__(
            handler, ToolList
        )
        handler._build_eval_context = ToolList._build_eval_context.__get__(
            handler, ToolList
        )
        handler.get = ToolList.get.__get__(handler, ToolList)
        handler.json_response = MagicMock(return_value={"status": 200})
        handler.error = MagicMock(return_value={"status": 400})

        return handler

    @pytest.mark.asyncio
    async def test_get_no_pbac_returns_all(self):
        """get() returns all tools when PDP absent (fail-open)."""
        handler = self._make_handler(has_pdp=False)

        mock_tools = {"tool_a": "path.a", "tool_b": "path.b"}

        with patch('parrot.handlers.bots._PBAC_AVAILABLE', False), \
             patch('parrot.handlers.bots.get_toolkit_resolver', return_value=_fake_resolver(mock_tools)):
            await handler.get()

        handler.json_response.assert_called_once()
        result = handler.json_response.call_args[0][0]
        assert "tools" in result
        assert len(result["tools"]) == 2

    @pytest.mark.asyncio
    async def test_get_filters_denied_tools(self):
        """get() filters out tools denied by PBAC."""
        handler = self._make_handler(has_pdp=True, allowed_tools=["tool_a"])

        mock_tools = {"tool_a": "path.a", "tool_b": "path.b"}

        with patch('parrot.handlers.bots._PBAC_AVAILABLE', True), \
             patch('parrot.handlers.bots._core_build_eval_context', AsyncMock(return_value=MagicMock())), \
             patch('parrot.handlers.bots._ResourceType', MagicMock(TOOL='TOOL')), \
             patch('parrot.handlers.bots.get_toolkit_resolver', return_value=_fake_resolver(mock_tools)):
            await handler.get()

        handler.json_response.assert_called_once()
        result = handler.json_response.call_args[0][0]
        # Only tool_a should be in the response
        assert "tool_a" in result["tools"]
        assert "tool_b" not in result["tools"]

    @pytest.mark.asyncio
    async def test_get_empty_tools(self):
        """get() handles empty tool list gracefully."""
        handler = self._make_handler(has_pdp=True)

        with patch('parrot.handlers.bots._PBAC_AVAILABLE', True), \
             patch('parrot.handlers.bots.get_toolkit_resolver', return_value=_fake_resolver({})):
            await handler.get()

        handler.json_response.assert_called_once()
        result = handler.json_response.call_args[0][0]
        assert result["tools"] == {}

    @pytest.mark.asyncio
    async def test_get_evaluator_error_fails_open(self):
        """get() returns all tools when evaluator raises (fail-open)."""
        handler = self._make_handler(has_pdp=True)
        handler.request.app.get.return_value._evaluator.filter_resources.side_effect = (
            RuntimeError("Evaluator crashed")
        )

        mock_tools = {"tool_a": "path.a", "tool_b": "path.b"}

        with patch('parrot.handlers.bots._PBAC_AVAILABLE', True), \
             patch('parrot.handlers.bots._core_build_eval_context', AsyncMock(return_value=MagicMock())), \
             patch('parrot.handlers.bots._ResourceType', MagicMock(TOOL='TOOL')), \
             patch('parrot.handlers.bots.get_toolkit_resolver', return_value=_fake_resolver(mock_tools)):
            # Should NOT raise — fail-open on evaluator errors
            await handler.get()

        handler.json_response.assert_called_once()
        result = handler.json_response.call_args[0][0]
        # All tools returned (fail-open)
        assert len(result["tools"]) == 2

    @pytest.mark.asyncio
    async def test_get_deny_all_returns_empty(self):
        """get() returns empty tools dict when evaluator returns allowed=[] (deny all).

        Regression test for the `or tool_names` bug: an empty allowed list must
        mean "deny all", NOT fall back to "allow all".
        """
        handler = self._make_handler(has_pdp=True, allowed_tools=[])  # deny all

        mock_tools = {"tool_a": "path.a", "tool_b": "path.b"}

        with patch('parrot.handlers.bots._PBAC_AVAILABLE', True), \
             patch('parrot.handlers.bots._core_build_eval_context', AsyncMock(return_value=MagicMock())), \
             patch('parrot.handlers.bots._ResourceType', MagicMock(TOOL='TOOL')), \
             patch('parrot.handlers.bots.get_toolkit_resolver', return_value=_fake_resolver(mock_tools)):
            await handler.get()

        handler.json_response.assert_called_once()
        result = handler.json_response.call_args[0][0]
        assert result["tools"] == {}, "deny-all must return empty dict, not all tools"


class TestToolListHostEntries:
    """Pins ``ToolList.get`` behaviour on dev (F7): host/walk entries are never listed, built-ins are."""

    @pytest.mark.asyncio
    async def test_host_and_walk_entries_are_not_listed(self):
        handler = TestToolListPBAC()._make_handler(has_pdp=False)
        resolver = _fake_resolver(
            {"tool_a": "path.a"},
            host={"acme_declared": ("plugins.tools.a.A", "host"), "acme_walked": (None, "walk")},
        )
        with patch('parrot.handlers.bots._PBAC_AVAILABLE', False), \
             patch('parrot.handlers.bots.get_toolkit_resolver', return_value=resolver):
            await handler.get()

        tools = handler.json_response.call_args[0][0]["tools"]
        assert set(tools) == {"tool_a"}
        assert tools["tool_a"] == {"tool_name": "tool_a", "module_path": "path.a"}

    @pytest.mark.asyncio
    async def test_builtin_entries_are_listed_from_their_class(self):
        from parrot.tools.resolver import ToolkitEntry

        class Fake:
            name = "wiki_tool"
            __doc__ = "A wiki."

        handler = TestToolListPBAC()._make_handler(has_pdp=False)
        resolver = MagicMock()
        resolver.entries.return_value = [ToolkitEntry(slug="wiki", dotted_path=None, source="builtin")]
        resolver.resolve.return_value = Fake
        with patch('parrot.handlers.bots._PBAC_AVAILABLE', False), \
             patch('parrot.handlers.bots.get_toolkit_resolver', return_value=resolver):
            await handler.get()

        tools = handler.json_response.call_args[0][0]["tools"]
        assert tools["wiki"]["tool_name"] == "wiki_tool"
        assert tools["wiki"]["module_path"].endswith("Fake")
        assert tools["wiki"]["description"] == "A wiki."
