"""Unit tests for parrot.auth.agent_guard — FEAT-153 TASK-1049.

Tests cover:
  - parse_bot_permissions: all accepted shapes + malformed rejection
  - enforce_agent_access: all allow-paths + deny-path
"""
from __future__ import annotations

import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.auth.agent_guard import (
    AgentAccessDenied,
    parse_bot_permissions,
    enforce_agent_access,
)
from parrot.auth.models import PolicyRuleConfig


class TestParseBotPermissions:
    """Unit tests for parse_bot_permissions."""

    def test_none_is_public(self):
        """None → empty list (public bot)."""
        assert parse_bot_permissions(None) == []

    def test_empty_dict_is_public(self):
        """Empty dict → empty list (public bot)."""
        assert parse_bot_permissions({}) == []

    def test_empty_permissions_key_is_public(self):
        """{'permissions': []} → empty list (public bot)."""
        assert parse_bot_permissions({"permissions": []}) == []

    def test_canonical_shape(self):
        """Canonical shape parses into a list of PolicyRuleConfig."""
        result = parse_bot_permissions({
            "permissions": [
                {
                    "action": "agent:resolve",
                    "effect": "allow",
                    "groups": ["engineering"],
                },
            ],
        })
        assert len(result) == 1
        assert isinstance(result[0], PolicyRuleConfig)
        assert result[0].action == "agent:resolve"
        assert result[0].effect == "allow"
        assert result[0].groups == ["engineering"]

    def test_bare_list_fallback(self):
        """Bare list → treated as 'permissions' value (forgiving fallback)."""
        result = parse_bot_permissions([
            {"action": "agent:resolve", "effect": "allow"},
        ])
        assert len(result) == 1
        assert isinstance(result[0], PolicyRuleConfig)

    def test_malformed_permissions_not_list_raises(self):
        """'permissions' key present but value is not a list → ValueError."""
        with pytest.raises(ValueError, match="must be a list"):
            parse_bot_permissions({"permissions": "not-a-list"})

    def test_invalid_rule_missing_action_raises(self):
        """Rule dict missing required 'action' field → ValueError."""
        with pytest.raises(ValueError):
            parse_bot_permissions({"permissions": [{"effect": "allow"}]})

    def test_string_input_raises(self):
        """String input → ValueError (not a dict or list)."""
        with pytest.raises(ValueError, match="expected dict or list"):
            parse_bot_permissions("string")  # type: ignore[arg-type]

    def test_integer_input_raises(self):
        """Integer input → ValueError (not a dict or list)."""
        with pytest.raises(ValueError, match="expected dict or list"):
            parse_bot_permissions(123)  # type: ignore[arg-type]

    def test_dict_missing_permissions_key_raises(self):
        """Non-empty dict without 'permissions' key → ValueError."""
        with pytest.raises(ValueError, match="must have 'permissions' key"):
            parse_bot_permissions({"other_key": "value"})

    def test_multiple_rules_parsed_correctly(self):
        """Multiple rules in canonical shape → all parsed."""
        result = parse_bot_permissions({
            "permissions": [
                {"action": "agent:resolve", "effect": "allow",
                 "groups": ["engineering"], "priority": 10},
                {"action": "agent:resolve", "effect": "deny",
                 "roles": ["contractors"], "priority": 100},
            ],
        })
        assert len(result) == 2
        assert result[0].effect == "allow"
        assert result[1].effect == "deny"
        assert result[1].roles == ["contractors"]
        assert result[1].priority == 100


class TestEnforceAgentAccess:
    """Unit tests for enforce_agent_access."""

    @pytest.mark.asyncio
    async def test_no_evaluator_allows(self):
        """evaluator=None → no exception (PBAC not initialized, backwards compat)."""
        req = MagicMock()
        # Must NOT raise
        await enforce_agent_access(None, "bot_x", request=req)

    @pytest.mark.asyncio
    async def test_no_request_allows_even_with_policies(self):
        """request=None → allows unconditionally (programmatic invocation bypass).

        The evaluator must NOT be queried — §8 Q1 resolved: PBAC enforcement
        is HTTP-scoped.
        """
        evaluator = MagicMock()
        evaluator.check_access.return_value = MagicMock(allowed=False)

        await enforce_agent_access(evaluator, "bot_x", request=None)

        # Evaluator must never have been consulted.
        evaluator.check_access.assert_not_called()

    @pytest.mark.asyncio
    async def test_allow_decision(self):
        """Evaluator returns allowed=True → no exception."""
        try:
            from navigator_auth.abac.policies.resources import ResourceType  # noqa: F401
            from navigator_auth.abac.policies.environment import Environment  # noqa: F401
            has_nav_auth = True
        except ImportError:
            has_nav_auth = False

        evaluator = MagicMock()
        evaluator.check_access.return_value = MagicMock(allowed=True)
        req = MagicMock()

        with patch(
            "parrot.auth.agent_guard._build_eval_context_from_request",
            new=AsyncMock(return_value=MagicMock()),
        ):
            # Must not raise regardless of whether navigator-auth is installed.
            await enforce_agent_access(evaluator, "bot_x", request=req)

        if has_nav_auth:
            evaluator.check_access.assert_called_once()
        else:
            # navigator-auth absent → fail open, evaluator not called
            evaluator.check_access.assert_not_called()

    @pytest.mark.asyncio
    async def test_deny_decision_raises_and_logs_warning(self, caplog):
        """Evaluator returns allowed=False + request is not None → AgentAccessDenied + WARNING."""
        result_mock = MagicMock()
        result_mock.allowed = False
        result_mock.matched_policy = "deny-contractors"
        result_mock.reason = "role contractors denied"

        evaluator = MagicMock()
        evaluator.check_access.return_value = result_mock

        req = MagicMock()
        eval_ctx_mock = MagicMock()
        eval_ctx_mock.username = "user-42"

        with patch(
            "parrot.auth.agent_guard._build_eval_context_from_request",
            new=AsyncMock(return_value=eval_ctx_mock),
        ):
            try:
                from navigator_auth.abac.policies.resources import ResourceType  # noqa
                from navigator_auth.abac.policies.environment import Environment  # noqa
                has_nav_auth = True
            except ImportError:
                has_nav_auth = False

            if not has_nav_auth:
                pytest.skip("navigator-auth not installed — skip deny-path test")

            with caplog.at_level(logging.WARNING, logger="parrot.auth.agent_guard"):
                with pytest.raises(AgentAccessDenied) as exc_info:
                    await enforce_agent_access(evaluator, "finance_bot", request=req)

        exc = exc_info.value
        assert exc.bot_name == "finance_bot"
        # Warning must have been emitted
        assert any("PBAC AGENT DENY" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_no_eval_context_allows_fail_open(self):
        """When eval context cannot be built (session absent) → fail open."""
        evaluator = MagicMock()
        req = MagicMock()

        with patch(
            "parrot.auth.agent_guard._build_eval_context_from_request",
            new=AsyncMock(return_value=None),
        ):
            # Must not raise even with a real evaluator
            await enforce_agent_access(evaluator, "bot_x", request=req)


class TestAgentAccessDenied:
    """Unit tests for AgentAccessDenied exception class."""

    def test_is_permission_error(self):
        """AgentAccessDenied is a subclass of PermissionError."""
        exc = AgentAccessDenied(bot_name="test_bot")
        assert isinstance(exc, PermissionError)

    def test_attributes_stored(self):
        """All constructor attributes are stored on the instance."""
        exc = AgentAccessDenied(
            bot_name="finance_bot",
            user_id="user-42",
            matched_policy="deny-all",
            reason="contractors denied",
        )
        assert exc.bot_name == "finance_bot"
        assert exc.user_id == "user-42"
        assert exc.matched_policy == "deny-all"
        assert exc.reason == "contractors denied"

    def test_default_attributes_none(self):
        """Optional attributes default to None."""
        exc = AgentAccessDenied(bot_name="bot")
        assert exc.user_id is None
        assert exc.matched_policy is None
        assert exc.reason is None

    def test_str_contains_bot_name(self):
        """str(exc) contains bot name."""
        exc = AgentAccessDenied(bot_name="finance_bot")
        assert "finance_bot" in str(exc)
