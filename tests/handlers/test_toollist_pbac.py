"""Unit tests for ToolList PBAC filtering (TASK-713)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestToolListPBAC:
    """Tests for ToolList.get() PBAC filtering."""

    def _make_handler(self, has_pdp: bool = True, allowed_tools=None):
        """Create a ToolList mock with configurable PDP state."""
        from parrot.handlers.bots import ToolList

        handler = MagicMock(spec=ToolList)

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
             patch('parrot.handlers.bots.discover_all', return_value=mock_tools):
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
             patch('parrot.handlers.bots._EvalContext', MagicMock(return_value=MagicMock())), \
             patch('parrot.handlers.bots._ResourceType', MagicMock(TOOL='TOOL')), \
             patch('parrot.handlers.bots.discover_all', return_value=mock_tools):
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
             patch('parrot.handlers.bots.discover_all', return_value={}):
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
             patch('parrot.handlers.bots._EvalContext', MagicMock(return_value=MagicMock())), \
             patch('parrot.handlers.bots._ResourceType', MagicMock(TOOL='TOOL')), \
             patch('parrot.handlers.bots.discover_all', return_value=mock_tools):
            # Should NOT raise — fail-open on evaluator errors
            await handler.get()

        handler.json_response.assert_called_once()
        result = handler.json_response.call_args[0][0]
        # All tools returned (fail-open)
        assert len(result["tools"]) == 2
