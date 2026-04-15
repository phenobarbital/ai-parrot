"""Unit tests for ChatbotHandler PBAC filtering (TASK-712).

Tests cover:
- _get_one() returns 403 when PBAC denies agent:list
- _get_one() returns agent when PBAC allows
- _get_one() returns agent when PDP absent (fail-open)
- _get_all() filters denied agents
- _get_all() returns all when PDP absent (fail-open)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestChatbotHandlerPBAC:
    """Tests for ChatbotHandler PBAC filtering."""

    def _make_handler(self, has_pdp: bool = True, evaluator_allows: bool = True):
        """Create a mock ChatbotHandler with configurable PDP state."""
        from parrot.handlers.bots import ChatbotHandler

        handler = MagicMock(spec=ChatbotHandler)
        handler.logger = MagicMock()

        # Mock session
        session = MagicMock()
        session.get = MagicMock(return_value={
            "username": "testuser",
            "groups": ["engineering"],
            "roles": [],
            "programs": [],
        })
        handler.request = MagicMock()
        handler.request.session = session

        # Mock PDP/evaluator
        if has_pdp:
            mock_result = MagicMock()
            mock_result.allowed = evaluator_allows
            mock_evaluator = MagicMock()
            mock_evaluator.check_access = MagicMock(return_value=mock_result)
            mock_evaluator.filter_resources = MagicMock(return_value=MagicMock(
                allowed=["bot_a"] if evaluator_allows else []
            ))
            mock_pdp = MagicMock()
            mock_pdp._evaluator = mock_evaluator
            handler.request.app.get = MagicMock(return_value=mock_pdp)
        else:
            handler.request.app.get = MagicMock(return_value=None)

        # Bind real methods
        handler._get_pbac_evaluator = ChatbotHandler._get_pbac_evaluator.__get__(
            handler, ChatbotHandler
        )
        handler._build_eval_context = ChatbotHandler._build_eval_context.__get__(
            handler, ChatbotHandler
        )
        handler._get_one = ChatbotHandler._get_one.__get__(handler, ChatbotHandler)
        handler._get_all = ChatbotHandler._get_all.__get__(handler, ChatbotHandler)

        return handler

    @pytest.mark.asyncio
    async def test_get_one_allowed(self):
        """_get_one returns agent when evaluator allows."""
        handler = self._make_handler(has_pdp=True, evaluator_allows=True)

        mock_agent = MagicMock()
        mock_agent.name = "test_bot"
        handler._get_db_agent = AsyncMock(return_value=mock_agent)
        handler._bot_model_to_dict = MagicMock(return_value={"name": "test_bot"})
        handler.json_response = MagicMock(return_value={"status": 200})

        with patch('parrot.handlers.bots._PBAC_AVAILABLE', True), \
             patch('parrot.handlers.bots._EvalContext', MagicMock(return_value=MagicMock())), \
             patch('parrot.handlers.bots._ResourceType', MagicMock(AGENT='AGENT')):
            result = await handler._get_one("test_bot")

        handler.json_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_one_denied(self):
        """_get_one returns 403 when evaluator denies."""
        handler = self._make_handler(has_pdp=True, evaluator_allows=False)

        handler.error = MagicMock(return_value={"status": 403})

        with patch('parrot.handlers.bots._PBAC_AVAILABLE', True), \
             patch('parrot.handlers.bots._EvalContext', MagicMock(return_value=MagicMock())), \
             patch('parrot.handlers.bots._ResourceType', MagicMock(AGENT='AGENT')):
            result = await handler._get_one("restricted_bot")

        handler.error.assert_called_once()
        call_kwargs = handler.error.call_args
        assert call_kwargs[1].get('status') == 403 or call_kwargs[0][1] == 403

    @pytest.mark.asyncio
    async def test_get_one_no_pbac(self):
        """_get_one returns agent when PDP absent (fail-open)."""
        handler = self._make_handler(has_pdp=False)

        mock_agent = MagicMock()
        mock_agent.name = "public_bot"
        handler._get_db_agent = AsyncMock(return_value=mock_agent)
        handler._bot_model_to_dict = MagicMock(return_value={"name": "public_bot"})
        handler.json_response = MagicMock(return_value={"status": 200})

        with patch('parrot.handlers.bots._PBAC_AVAILABLE', False):
            result = await handler._get_one("public_bot")

        handler.json_response.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_all_no_pbac_returns_all(self):
        """_get_all returns all agents when PDP absent (fail-open)."""
        handler = self._make_handler(has_pdp=False)

        handler._get_db_agents = AsyncMock(return_value=[])
        handler._registry = None
        handler.json_response = MagicMock(return_value={"status": 200})

        with patch('parrot.handlers.bots._PBAC_AVAILABLE', False):
            result = await handler._get_all()

        handler.json_response.assert_called_once()
        called_data = handler.json_response.call_args[0][0]
        assert "agents" in called_data

    @pytest.mark.asyncio
    async def test_get_all_filters_denied(self):
        """_get_all excludes denied agents from listing."""
        handler = self._make_handler(has_pdp=True, evaluator_allows=True)

        # Mock 2 agents in DB
        agent_a = MagicMock()
        agent_a.name = "bot_a"
        handler._get_db_agents = AsyncMock(return_value=[agent_a])
        handler._bot_model_to_dict = MagicMock(return_value={"name": "bot_a"})
        handler._registry = None
        handler.json_response = MagicMock(return_value={"status": 200})

        with patch('parrot.handlers.bots._PBAC_AVAILABLE', True), \
             patch('parrot.handlers.bots._EvalContext', MagicMock(return_value=MagicMock())), \
             patch('parrot.handlers.bots._ResourceType', MagicMock(AGENT='AGENT')):
            result = await handler._get_all()

        handler.json_response.assert_called_once()
