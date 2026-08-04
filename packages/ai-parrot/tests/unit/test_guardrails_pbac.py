"""Unit tests for `PBACToolCallGuardrail` (FEAT-406 / TASK-2110).

Covers ALLOW/DENY mapping, missing `permission_context` passthrough,
engine-error fail-closed default, per-policy `enforcement: fail_open`
downgrade, and `"pbac"` registry registration.

`PolicyEvaluator.check_access()` is synchronous and returns an
`EvaluationResult` dataclass (`allowed`, `matched_policy`, `reason`) — NOT
the `PolicyResponse` shape returned by lower-level `ResourcePolicy` methods.
Mocked accordingly (`MagicMock`, not `AsyncMock`), mirroring
`tests/auth/test_pbac_resolver.py`'s existing convention.
"""
from unittest.mock import MagicMock

import pytest

from parrot.auth.permission import PermissionContext, UserSession
from parrot.bots.guardrails.base import (
    GuardrailAction,
    GuardrailContext,
    GuardrailStage,
)
from parrot.bots.guardrails.builtin.pbac import (
    PBACToolCallGuardrail,
    PolicyDenialReport,
)
from parrot.bots.guardrails.registry import _GUARDRAIL_FACTORIES, build_guardrails


def _make_eval_result(allowed: bool, policy: str = "test_policy", reason: str = ""):
    """Create a minimal EvaluationResult mock (mirrors test_pbac_resolver.py)."""
    result = MagicMock()
    result.allowed = allowed
    result.matched_policy = policy
    result.reason = reason
    return result


def _make_permission_context(user_id: str = "user-1") -> PermissionContext:
    session = UserSession(user_id=user_id, tenant_id="acme", roles=frozenset({"engineer"}))
    return PermissionContext(session=session)


def _make_ctx(permission_context=None, tool_name: str = "some_tool") -> GuardrailContext:
    extras = {}
    if permission_context is not None:
        extras["permission_context"] = permission_context
    return GuardrailContext(
        stage=GuardrailStage.TOOL_CALL,
        agent_name="test-agent",
        user_id="user-1",
        tool_name=tool_name,
        extras=extras,
    )


class TestPBACToolCallGuardrailBasics:
    def test_class_attributes(self):
        assert PBACToolCallGuardrail.name == "pbac"
        assert GuardrailStage.TOOL_CALL in PBACToolCallGuardrail.stages
        assert PBACToolCallGuardrail.priority == 10
        assert PBACToolCallGuardrail.on_error == "fail_closed"


class TestPBACToolCallGuardrailCheck:
    @pytest.mark.asyncio
    async def test_pbac_allow_maps_to_pass(self):
        pytest.importorskip("navigator_auth")
        evaluator = MagicMock()
        evaluator.check_access.return_value = _make_eval_result(True)
        guardrail = PBACToolCallGuardrail(evaluator=evaluator)
        ctx = _make_ctx(_make_permission_context())

        result = await guardrail.check("irrelevant", ctx)

        assert result.action == GuardrailAction.PASS
        assert result.content is None

    @pytest.mark.asyncio
    async def test_pbac_deny_maps_to_block_with_report(self):
        pytest.importorskip("navigator_auth")
        evaluator = MagicMock()
        evaluator.check_access.return_value = _make_eval_result(
            False, policy="business_hours", reason="outside business hours"
        )
        guardrail = PBACToolCallGuardrail(evaluator=evaluator)
        ctx = _make_ctx(_make_permission_context(), tool_name="admin_tool")

        result = await guardrail.check("irrelevant", ctx)

        assert result.action == GuardrailAction.BLOCK
        assert result.reason == "policy:business_hours"
        assert result.report is not None
        report = PolicyDenialReport(**result.report)
        assert report.rule == "business_hours"
        assert report.message == "outside business hours"
        assert report.tool_name == "admin_tool"

    @pytest.mark.asyncio
    async def test_pbac_no_permission_context_passes(self):
        evaluator = MagicMock()
        guardrail = PBACToolCallGuardrail(evaluator=evaluator)
        ctx = _make_ctx(permission_context=None)

        result = await guardrail.check("irrelevant", ctx)

        assert result.action == GuardrailAction.PASS
        evaluator.check_access.assert_not_called()

    @pytest.mark.asyncio
    async def test_pbac_engine_error_fail_closed(self):
        pytest.importorskip("navigator_auth")
        evaluator = MagicMock()
        evaluator.check_access.side_effect = RuntimeError("engine boom")
        evaluator._index = MagicMock()
        evaluator._index.get_for_resource_type.return_value = []
        guardrail = PBACToolCallGuardrail(evaluator=evaluator)
        ctx = _make_ctx(_make_permission_context())

        result = await guardrail.check("irrelevant", ctx)

        assert result.action == GuardrailAction.BLOCK
        assert result.reason == "policy_engine_unavailable"
        assert result.report["rule"] == "policy_engine_unavailable"

    @pytest.mark.asyncio
    async def test_pbac_enforcement_fail_open_downgrade(self):
        pytest.importorskip("navigator_auth")
        from navigator_auth.abac.policies.resources import ResourceType

        evaluator = MagicMock()
        evaluator.check_access.side_effect = RuntimeError("engine boom")

        matching_policy = MagicMock()
        matching_policy.covers_resource.return_value = True
        matching_policy.attributes = {"enforcement": "fail_open"}

        evaluator._index = MagicMock()

        def _get_for_resource_type(rtype):
            assert rtype == ResourceType.TOOL
            return [matching_policy]

        evaluator._index.get_for_resource_type.side_effect = _get_for_resource_type

        guardrail = PBACToolCallGuardrail(evaluator=evaluator)
        ctx = _make_ctx(_make_permission_context(), tool_name="flaky_tool")

        result = await guardrail.check("irrelevant", ctx)

        assert result.action == GuardrailAction.PASS


class TestPBACRegistryRegistration:
    def test_pbac_registered_in_factories(self):
        assert "pbac" in _GUARDRAIL_FACTORIES

    def test_build_guardrails_by_name_lazy_imports_pbac(self):
        evaluator = MagicMock()
        guardrails = build_guardrails([{"name": "pbac", "evaluator": evaluator}])
        assert len(guardrails) == 1
        assert isinstance(guardrails[0], PBACToolCallGuardrail)
