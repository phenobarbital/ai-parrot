"""End-to-end integration tests for FEAT-406 PBAC Guardrails (TASK-2114).

Exercises `PBACToolCallGuardrail` against a REAL `PolicyEvaluator` loaded
from an on-disk policy YAML (mirroring `policies/tool-business-hours.yaml`),
with a frozen `Environment` clock, verifying:

- Business-hours DENY: outside the window -> forbidden; inside -> passes.
- Per-policy `enforcement: fail_open` downgrade on an engine error
  (constructed directly on a `ResourcePolicy`, per the documented
  navigator-auth YAML-loader gap — see docs/security/pbac-guardrails.md).
- Telemetry never carries content/tool arguments.
- `UserInfo`/`UserProfileKB` KB regression (unchanged, still importable
  and structurally intact with the feature enabled).
- `PBACPermissionResolver` (Layer 2) remains active alongside the guardrail
  (defense-in-depth, resolved spec Q4).
- Tool-call arguments are never projected into policy evaluation.
"""
from pathlib import Path
from unittest.mock import MagicMock

import navigator_auth.abac.policies.environment as _env_mod
import pytest
from navigator_auth.abac.policies.abstract import PolicyEffect
from navigator_auth.abac.policies.evaluator import PolicyEvaluator
from navigator_auth.abac.policies.resource_policy import ResourcePolicy

from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.resolver import PBACPermissionResolver
from parrot.bots.guardrails.base import (
    GuardrailAction,
    GuardrailContext,
    GuardrailStage,
)
from parrot.bots.guardrails.builtin.pbac import PBACToolCallGuardrail
from parrot.bots.guardrails.pipeline import GuardrailPipeline
from parrot.stores.kb.user import UserInfo, UserProfileKB

pytest.importorskip("navigator_auth")

_RealEnvironment = _env_mod.Environment


# ── Fixtures ─────────────────────────────────────────────────────────────────


_SAMPLE_POLICY_YAML = """
version: "1.0"
defaults:
  effect: deny
policies:
  - name: demo_business_hours_tool_allow_baseline
    effect: allow
    resources:
      - "tool:demo_business_hours_only"
    actions:
      - "tool:execute"
    subjects:
      groups:
        - "*"
    priority: 5
  - name: demo_business_hours_tool_deny
    effect: deny
    resources:
      - "tool:demo_business_hours_only"
    actions:
      - "tool:execute"
    subjects:
      groups:
        - "*"
    conditions:
      environment:
        is_business_hours: false
    enforcement: fail_closed
    priority: 5
"""


@pytest.fixture
def shared_evaluator(tmp_path: Path) -> PolicyEvaluator:
    """A real PolicyEvaluator loaded from the sample business-hours policy."""
    policy_file = tmp_path / "tool-business-hours.yaml"
    policy_file.write_text(_SAMPLE_POLICY_YAML)
    evaluator = PolicyEvaluator(cache_size=64, cache_ttl_seconds=30)
    evaluator.load_from_file(policy_file)
    return evaluator


class _FrozenEnvironmentFactory:
    """Callable replacing `Environment` with a fixed-clock instance.

    `PBACToolCallGuardrail.check()` imports `Environment` lazily (function-
    local `from navigator_auth.abac.policies.environment import
    Environment`), so patching the module attribute is picked up on every
    call — no recursion risk since `_RealEnvironment` was captured BEFORE
    patching.
    """

    def __init__(self, **overrides):
        self._overrides = overrides

    def __call__(self, *args, **kwargs):
        return _RealEnvironment(**self._overrides)


@pytest.fixture
def frozen_environment(monkeypatch):
    """Patch `Environment` construction to a deterministic inside/outside
    business-hours instant. Returns a setter you call with the desired
    hour/dow."""

    def _freeze(hour: int, dow: int = 0, minute: int = 0):
        monkeypatch.setattr(
            _env_mod, "Environment",
            _FrozenEnvironmentFactory(hour=hour, minute=minute, dow=dow),
        )

    return _freeze


def _make_permission_context(user_id: str = "user-1") -> PermissionContext:
    session = UserSession(user_id=user_id, tenant_id="acme", roles=frozenset({"engineer"}))
    return PermissionContext(session=session)


def _make_ctx(permission_context, tool_name: str, arguments: dict | None = None) -> GuardrailContext:
    return GuardrailContext(
        stage=GuardrailStage.TOOL_CALL,
        agent_name="test-agent",
        user_id="user-1",
        tool_name=tool_name,
        extras={
            "permission_context": permission_context,
            "tool_name": tool_name,
            "arguments": arguments or {},
        },
    )


# ── Business-hours DENY e2e ──────────────────────────────────────────────────


class TestBusinessHoursE2E:
    @pytest.mark.asyncio
    async def test_business_hours_deny_e2e_outside_window(self, shared_evaluator, frozen_environment):
        """Outside business hours (22:00 Monday) -> BLOCK with operator message."""
        frozen_environment(hour=22, dow=0)  # Monday 22:00 — outside 08:00-18:00
        guardrail = PBACToolCallGuardrail(evaluator=shared_evaluator)
        ctx = _make_ctx(_make_permission_context(), "demo_business_hours_only")

        result = await guardrail.check("tool_call:demo_business_hours_only", ctx)

        assert result.action == GuardrailAction.BLOCK
        assert result.reason == "policy:demo_business_hours_tool_deny"
        assert result.report is not None

    @pytest.mark.asyncio
    async def test_business_hours_deny_e2e_inside_window(self, shared_evaluator, frozen_environment):
        """Inside business hours (10:00 Monday) -> PASS, tool would execute."""
        frozen_environment(hour=10, dow=0)  # Monday 10:00 — inside 08:00-18:00
        guardrail = PBACToolCallGuardrail(evaluator=shared_evaluator)
        ctx = _make_ctx(_make_permission_context(), "demo_business_hours_only")

        result = await guardrail.check("tool_call:demo_business_hours_only", ctx)

        assert result.action == GuardrailAction.PASS

    @pytest.mark.asyncio
    async def test_business_hours_fail_open_downgrade(self, shared_evaluator):
        """Deciding policy has enforcement=fail_open -> engine error passes through.

        `enforcement:` is not forwarded by the YAML loader (documented
        navigator-auth gap) — this constructs the ResourcePolicy directly
        with the extra kwarg to exercise the actual downgrade path, mirroring
        `PBACToolCallGuardrail._policy_enforcement()`'s real lookup against
        the evaluator's PolicyIndex (not a mock).
        """
        soft_policy = ResourcePolicy(
            name="demo_business_hours_tool_deny_soft",
            effect=PolicyEffect.DENY,
            resources=["tool:demo_business_hours_only_soft"],
            actions=["tool:execute"],
            subjects={"groups": ["*"]},
            environment={"is_business_hours": False},
            priority=5,
            enforcement="fail_open",  # extra kwarg -> ResourcePolicy.attributes
        )
        shared_evaluator.load_policies([soft_policy])
        guardrail = PBACToolCallGuardrail(evaluator=shared_evaluator)
        guardrail._evaluator.check_access = MagicMock(side_effect=RuntimeError("engine boom"))
        ctx = _make_ctx(_make_permission_context(), "demo_business_hours_only_soft")

        result = await guardrail.check("tool_call:demo_business_hours_only_soft", ctx)

        assert result.action == GuardrailAction.PASS

    @pytest.mark.asyncio
    async def test_engine_error_via_real_check_access_never_leaks_raw_message(
        self, shared_evaluator, frozen_environment, monkeypatch,
    ):
        """Drives a genuine Rust-engine failure through the REAL,
        unmodified `PolicyEvaluator.check_access()` (not a mocked
        `check_access`) — `check_access()` catches its own
        `evaluate_single()` exception internally and returns a normal DENY
        `EvaluationResult` instead of raising (code-review finding,
        TASK-2114 follow-up). Verifies the guardrail detects this and
        never surfaces the raw internal error text to the LLM.
        """
        frozen_environment(hour=10, dow=0)  # inside business hours — would ALLOW otherwise
        import navigator_auth.abac.policies.evaluator as evaluator_mod

        def _boom(*args, **kwargs):
            raise RuntimeError("rust panic: totally-internal-detail")

        monkeypatch.setattr(evaluator_mod, "evaluate_single", _boom)
        guardrail = PBACToolCallGuardrail(evaluator=shared_evaluator)
        ctx = _make_ctx(_make_permission_context(), "demo_business_hours_only")

        result = await guardrail.check("tool_call:demo_business_hours_only", ctx)

        assert result.action == GuardrailAction.BLOCK
        assert result.reason == "policy_engine_unavailable"
        assert "totally-internal-detail" not in str(result.report)
        assert "totally-internal-detail" not in (result.reason or "")


# ── Telemetry ────────────────────────────────────────────────────────────────


class TestTelemetry:
    @pytest.mark.asyncio
    async def test_telemetry_no_content(self, shared_evaluator, frozen_environment):
        frozen_environment(hour=22, dow=0)
        telemetry_entries = []
        pipeline = GuardrailPipeline(on_telemetry=telemetry_entries.append)
        pipeline.add(PBACToolCallGuardrail(evaluator=shared_evaluator))
        ctx = _make_ctx(
            _make_permission_context(), "demo_business_hours_only",
            arguments={"secret_arg": "should-never-appear-in-telemetry"},
        )

        outcome = await pipeline.run("tool_call:demo_business_hours_only", ctx)

        assert outcome.blocked is True
        assert len(telemetry_entries) == 1
        entry = telemetry_entries[0]
        assert entry.name == "pbac"
        assert entry.stage == GuardrailStage.TOOL_CALL
        assert entry.action == GuardrailAction.BLOCK
        assert isinstance(entry.duration_ms, float)
        # GuardrailTelemetryEntry has exactly these fields — no content/args.
        assert set(entry.model_dump().keys()) == {"name", "stage", "action", "duration_ms"}


# ── Regressions ──────────────────────────────────────────────────────────────


class TestRegressions:
    def test_kb_regression(self):
        """UserInfo/UserProfileKB remain importable and structurally unchanged
        (deprecation notes are docstring-only)."""
        user_info = UserInfo()
        profile_kb = UserProfileKB()

        assert callable(user_info.search)
        assert callable(profile_kb.search)
        assert "UserInfoService" in (UserInfo.__doc__ or "")
        assert "UserInfoService" in (UserProfileKB.__doc__ or "")

    @pytest.mark.asyncio
    async def test_layer2_resolver_still_active(self, shared_evaluator, frozen_environment):
        """PBACPermissionResolver.can_execute is still invoked/functional
        alongside the guardrail — both share the same evaluator (Q4)."""
        frozen_environment(hour=10, dow=0)  # inside business hours -> allowed
        resolver = PBACPermissionResolver(evaluator=shared_evaluator)
        ctx = _make_permission_context()

        allowed = await resolver.can_execute(ctx, "demo_business_hours_only", set())

        assert allowed is True

    @pytest.mark.asyncio
    async def test_arguments_not_in_policy_attributes(self, shared_evaluator, frozen_environment):
        """Tool-call arguments in ctx.extras['arguments'] are never read by
        the guardrail or projected into the evaluator's check_access call."""
        frozen_environment(hour=10, dow=0)
        guardrail = PBACToolCallGuardrail(evaluator=shared_evaluator)
        recorder = MagicMock(wraps=shared_evaluator.check_access)
        guardrail._evaluator.check_access = recorder
        ctx = _make_ctx(
            _make_permission_context(), "demo_business_hours_only",
            arguments={"password": "hunter2", "ssn": "000-00-0000"},
        )

        await guardrail.check("tool_call:demo_business_hours_only", ctx)

        assert recorder.called
        _, call_kwargs = recorder.call_args
        # Only ctx/resource_type/resource_name/action/env are passed — no
        # tool arguments anywhere in the call.
        assert "arguments" not in call_kwargs
        for value in call_kwargs.values():
            assert "hunter2" not in str(value)
            assert "000-00-0000" not in str(value)
