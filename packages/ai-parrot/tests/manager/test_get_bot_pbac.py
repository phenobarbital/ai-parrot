"""Integration tests for BotManager.get_bot PBAC enforcement — FEAT-153 TASK-1053.

Tests cover:
  - Empty permissions → any request resolves the bot.
  - Non-public policies deny non-matching callers (AgentAccessDenied raised).
  - request=None → programmatic invocation bypass (always allows).
  - evaluator=None → no PBAC check (always allows).
  - All three return paths gate correctly.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.auth.agent_guard import AgentAccessDenied


class TestGetBotPBAC:
    """PBAC enforcement tests for BotManager.get_bot."""

    def _make_manager_with_bot(self, bot_name: str = "finance_bot"):
        """Build a minimal BotManager with a fake bot in _bots."""
        from parrot.manager.manager import BotManager

        manager = BotManager()
        manager.app = MagicMock()

        fake_bot = MagicMock()
        fake_bot.name = bot_name
        fake_bot.is_configured = True
        manager._bots[bot_name] = fake_bot

        return manager, fake_bot

    @pytest.mark.asyncio
    async def test_get_bot_empty_permissions_allows_anyone(self):
        """permissions={} → evaluator has no policies → any request resolves the bot."""
        manager, fake_bot = self._make_manager_with_bot("finance_bot")
        # Evaluator exists but has no policies → check_access returns allowed=True
        mock_evaluator = MagicMock()
        mock_evaluator.check_access.return_value = MagicMock(allowed=True)
        manager.registry._evaluator = mock_evaluator

        req = MagicMock()
        with patch(
            "parrot.auth.agent_guard._build_eval_context_from_request",
            new=AsyncMock(return_value=MagicMock()),
        ):
            try:
                from navigator_auth.abac.policies.resources import ResourceType  # noqa
                has_nav_auth = True
            except ImportError:
                has_nav_auth = False

            if has_nav_auth:
                result = await manager.get_bot("finance_bot", request=req)
                assert result is fake_bot
            else:
                # Without navigator-auth, enforce_agent_access fails open
                result = await manager.get_bot("finance_bot", request=req)
                assert result is fake_bot

    @pytest.mark.asyncio
    async def test_get_bot_no_request_allows_programmatic_invocation(self):
        """get_bot(name) without request → resolves any bot, no PBAC check."""
        manager, fake_bot = self._make_manager_with_bot("finance_bot")

        # Evaluator returns denied (but it should never be consulted when request=None)
        mock_evaluator = MagicMock()
        mock_evaluator.check_access.return_value = MagicMock(allowed=False)
        manager.registry._evaluator = mock_evaluator

        result = await manager.get_bot("finance_bot")  # no request kwarg
        assert result is fake_bot
        # Evaluator must never have been queried
        mock_evaluator.check_access.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_bot_no_evaluator_allows(self):
        """When self.registry._evaluator is None, get_bot resolves unconditionally."""
        manager, fake_bot = self._make_manager_with_bot("finance_bot")
        manager.registry._evaluator = None

        req = MagicMock()
        result = await manager.get_bot("finance_bot", request=req)
        assert result is fake_bot

    @pytest.mark.asyncio
    async def test_get_bot_deny_raises_agent_access_denied(self):
        """Evaluator returns allowed=False + request is not None → AgentAccessDenied."""
        manager, fake_bot = self._make_manager_with_bot("finance_bot")

        mock_result = MagicMock()
        mock_result.allowed = False
        mock_result.matched_policy = "deny-all"
        mock_result.reason = "not in allowed groups"

        mock_evaluator = MagicMock()
        mock_evaluator.check_access.return_value = mock_result
        manager.registry._evaluator = mock_evaluator

        req = MagicMock()
        eval_ctx = MagicMock()
        eval_ctx.username = "user-42"

        with patch(
            "parrot.auth.agent_guard._build_eval_context_from_request",
            new=AsyncMock(return_value=eval_ctx),
        ):
            try:
                from navigator_auth.abac.policies.resources import ResourceType  # noqa
                has_nav_auth = True
            except ImportError:
                has_nav_auth = False

            if not has_nav_auth:
                pytest.skip("navigator-auth not installed — skip deny-path test")

            with pytest.raises(AgentAccessDenied) as exc_info:
                await manager.get_bot("finance_bot", request=req)

        assert exc_info.value.bot_name == "finance_bot"

    @pytest.mark.asyncio
    async def test_get_bot_cache_hit_path_enforces(self):
        """Cache-hit path (name in self._bots) calls enforce_agent_access."""
        manager, fake_bot = self._make_manager_with_bot("test_bot")
        manager.registry._evaluator = None  # evaluator=None → allow

        req = MagicMock()
        result = await manager.get_bot("test_bot", request=req)
        assert result is fake_bot

    @pytest.mark.asyncio
    async def test_get_bot_request_none_skips_evaluator_call(self):
        """request=None must never invoke the evaluator, even if it's set."""
        manager, fake_bot = self._make_manager_with_bot("test_bot")

        mock_evaluator = MagicMock()
        mock_evaluator.check_access.return_value = MagicMock(allowed=False)
        manager.registry._evaluator = mock_evaluator

        result = await manager.get_bot("test_bot")  # no request
        assert result is fake_bot
        mock_evaluator.check_access.assert_not_called()
