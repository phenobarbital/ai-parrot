"""Integration tests for AgentRegistry.get_instance PBAC enforcement — FEAT-153 TASK-1054.

Tests cover:
  - Empty/absent evaluator → any request resolves the bot (allow).
  - Evaluator returns allowed=True → resolves the bot.
  - Evaluator returns allowed=False + request present → AgentAccessDenied raised.
  - request=None → programmatic bypass, evaluator never consulted.
  - AgentAccessDenied propagates (NOT swallowed by the existing try/except).
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.registry.registry import AgentRegistry
from parrot.auth.agent_guard import AgentAccessDenied


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _registry_with_fake_bot(bot_name: str = "finance_bot") -> tuple[AgentRegistry, MagicMock]:
    """Build an AgentRegistry with a fake BotMetadata entry."""
    reg = AgentRegistry()

    fake_instance = MagicMock()
    fake_instance.name = bot_name

    fake_metadata = MagicMock()
    fake_metadata.get_instance = AsyncMock(return_value=fake_instance)
    reg._registered_agents[bot_name] = fake_metadata

    return reg, fake_instance


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetInstancePBAC:
    """PBAC enforcement tests for AgentRegistry.get_instance."""

    @pytest.mark.asyncio
    async def test_get_instance_no_evaluator_allows(self):
        """When self._evaluator is None, get_instance resolves unconditionally."""
        reg, fake_instance = _registry_with_fake_bot("finance_bot")
        reg._evaluator = None

        req = MagicMock()
        result = await reg.get_instance("finance_bot", request=req)
        assert result is fake_instance

    @pytest.mark.asyncio
    async def test_get_instance_no_request_allows_programmatic_invocation(self):
        """get_instance(name) without request → resolves bot, evaluator not called."""
        reg, fake_instance = _registry_with_fake_bot("finance_bot")

        mock_evaluator = MagicMock()
        mock_evaluator.check_access.return_value = MagicMock(allowed=False)
        reg._evaluator = mock_evaluator

        result = await reg.get_instance("finance_bot")  # no request kwarg
        assert result is fake_instance
        mock_evaluator.check_access.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_instance_empty_permissions_allows_anyone(self):
        """Evaluator present but allows → instance returned."""
        reg, fake_instance = _registry_with_fake_bot("finance_bot")
        mock_evaluator = MagicMock()
        mock_evaluator.check_access.return_value = MagicMock(allowed=True)
        reg._evaluator = mock_evaluator

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

            result = await reg.get_instance("finance_bot", request=req)
            assert result is fake_instance

    @pytest.mark.asyncio
    async def test_get_instance_deny_raises_agent_access_denied(self):
        """Evaluator returns allowed=False + request present → AgentAccessDenied."""
        reg, _ = _registry_with_fake_bot("finance_bot")

        mock_result = MagicMock()
        mock_result.allowed = False
        mock_result.matched_policy = "deny-all"
        mock_result.reason = "not in allowed groups"

        mock_evaluator = MagicMock()
        mock_evaluator.check_access.return_value = mock_result
        reg._evaluator = mock_evaluator

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
                await reg.get_instance("finance_bot", request=req)

        assert exc_info.value.bot_name == "finance_bot"

    @pytest.mark.asyncio
    async def test_get_instance_propagates_access_denied_not_swallowed(self):
        """AgentAccessDenied must NOT be caught by the existing try/except.

        The existing try/except around metadata.get_instance() returns None
        on failure.  After TASK-1054 the enforcement runs OUTSIDE that block,
        so AgentAccessDenied must propagate to the caller, not become None.
        """
        reg, _ = _registry_with_fake_bot("finance_bot")

        # We patch enforce_agent_access directly to raise AgentAccessDenied
        # without needing navigator-auth installed.
        with patch(
            "parrot.auth.agent_guard.enforce_agent_access",
            new=AsyncMock(side_effect=AgentAccessDenied(bot_name="finance_bot")),
        ):
            req = MagicMock()
            # Re-import after patching to pick up the patched version
            from parrot.auth import agent_guard
            original = agent_guard.enforce_agent_access
            with patch(
                "parrot.registry.registry.enforce_agent_access",
                new=AsyncMock(side_effect=AgentAccessDenied(bot_name="finance_bot")),
            ):
                with pytest.raises(AgentAccessDenied):
                    await reg.get_instance("finance_bot", request=req)
