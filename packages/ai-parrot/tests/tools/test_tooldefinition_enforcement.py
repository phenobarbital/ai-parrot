"""Unit tests for FEAT-474 — ToolManager ToolDefinition enforcement parity.

This module holds the shared unit-test surface for the feature (Modules
1-3): ToolDefinition model defaults, @tool decorator metadata, registration
metadata preservation, and execute_tool() enforcement parity. Tests are
added incrementally as each task lands; TASK-2578 covers the model +
decorator foundation, TASK-2579 registration metadata preservation, and
TASK-2580 (this addition) the core execute_tool() enforcement parity —
guardrail hoist, ConfirmationGuard, manager-level resolver gate, and the
uniform enforcement logger.
"""

import logging
from types import SimpleNamespace
from typing import ClassVar

import pytest
from parrot.auth.confirmation import ConfirmationGuard, InMemoryConfirmationWindowStore
from parrot.auth.resolver import AbstractPermissionResolver
from parrot.bots.guardrails.base import (
    Guardrail,
    GuardrailAction,
    GuardrailContext,
    GuardrailResult,
    GuardrailStage,
)
from parrot.bots.guardrails.pipeline import GuardrailPipeline
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.decorators import tool
from parrot.tools.manager import ToolDefinition, ToolManager


class TestToolDefinitionModel:
    """ToolDefinition dataclass defaults and slot behaviour (FEAT-474 G3)."""

    def test_legacy_keyword_construction(self):
        td = ToolDefinition(name="t", description="d", input_schema={}, function=lambda: 1)
        assert td.routing_meta == {}
        assert td.required_permissions == set()

    def test_legacy_positional_construction(self):
        td = ToolDefinition("t", "d", {}, lambda: 1)
        assert td.required_permissions == set()

    def test_slots_no_dict(self):
        td = ToolDefinition("t", "d", {}, lambda: 1)
        assert not hasattr(td, "__dict__")

    def test_defaults_not_shared_between_instances(self):
        a = ToolDefinition("a", "d", {}, lambda: 1)
        b = ToolDefinition("b", "d", {}, lambda: 1)
        a.routing_meta["k"] = "v"
        assert b.routing_meta == {}


class TestToolDecoratorRequiredPermissions:
    """@tool decorator required_permissions support (FEAT-474 G3)."""

    def test_required_permissions_stored(self):
        @tool(required_permissions={"reports:read"})
        def f(x: int) -> str:
            """Doc."""
            return str(x)

        assert f._tool_metadata["required_permissions"] == {"reports:read"}

    def test_default_empty(self):
        @tool
        def g(x: int) -> str:
            """Doc."""
            return str(x)

        assert g._tool_metadata["required_permissions"] == set()

    def test_routing_meta_still_built(self):
        @tool(requires_confirmation=True, confirm_window_seconds=30)
        def h(x: int) -> str:
            """Doc."""
            return str(x)

        assert h._tool_metadata["routing_meta"]["requires_confirmation"] is True


class TestRegistrationMetadata:
    """Registration preserves routing_meta/required_permissions (FEAT-474 G2/G5)."""

    def test_manager_preserves_routing_meta(self):
        tm = ToolManager()

        @tool(requires_confirmation=True, required_permissions={"p"})
        def f(x: int) -> str:
            """Doc."""
            return str(x)

        tm.register_tool(f)
        td = tm.get_tool("f")
        assert td.routing_meta["requires_confirmation"] is True
        assert td.required_permissions == {"p"}

    def test_inert_grant_warning(self, caplog):
        tm = ToolManager()
        td = ToolDefinition(
            "g",
            "d",
            {},
            lambda: 1,
            routing_meta={"requires_grant": True},
        )
        with caplog.at_level(logging.WARNING):
            tm.register_tool(td)
        assert any("grant" in r.message.lower() for r in caplog.records)

    def test_no_warning_for_confirmation_only(self, caplog):
        tm = ToolManager()
        td = ToolDefinition(
            "h",
            "d",
            {},
            lambda: 1,
            routing_meta={"requires_confirmation": True},
        )
        with caplog.at_level(logging.WARNING):
            tm.register_tool(td)
        assert not any("grant" in r.message.lower() for r in caplog.records)

    def test_inert_grant_warning_dict_construction_path(self, caplog):
        """The dict-based ToolDefinition construction site (register_tool's
        `isinstance(tool, dict)` branch) also warns on requires_grant — not
        just the direct-ToolDefinition accept-path (code-review finding)."""
        tm = ToolManager()
        with caplog.at_level(logging.WARNING):
            tm.register_tool(
                tool={
                    "name": "dict_tool",
                    "description": "d",
                    "parameters": {},
                    "_tool_instance": lambda: 1,
                    "routing_meta": {"requires_grant": True},
                }
            )
        assert any("grant" in r.message.lower() for r in caplog.records)

    def test_inert_grant_warning_tool_function_conversion_path(self, caplog):
        """The @tool-decorated-function conversion site (register_tool's
        callable/_tool_metadata branch) also warns on requires_grant, even
        though the @tool decorator itself has no requires_grant parameter —
        defense in depth for hand-tampered _tool_metadata (code-review
        finding)."""
        tm = ToolManager()

        @tool
        def f(x: int) -> str:
            """Doc."""
            return str(x)

        f._tool_metadata["routing_meta"]["requires_grant"] = True

        with caplog.at_level(logging.WARNING):
            tm.register_tool(f)
        assert any("grant" in r.message.lower() for r in caplog.records)

    def test_interfaces_tools_preserves_routing_meta(self):
        """`ToolInterface._initialize_tools()`'s @tool conversion site (the
        2nd construction site, interfaces/tools.py:77) preserves routing_meta
        and required_permissions identically to the manager.py path."""
        from parrot.interfaces.tools import ToolInterface

        class _Harness(ToolInterface):
            def __init__(self) -> None:
                self.logger = logging.getLogger("test.harness")
                self.tool_manager = ToolManager(logger=self.logger)

            def _capture_knowledge_toolkit(self, instance) -> None:
                pass

        @tool(requires_confirmation=True, required_permissions={"p"})
        def i(x: int) -> str:
            """Doc."""
            return str(x)

        harness = _Harness()
        harness._initialize_tools([i])
        td = harness.tool_manager.get_tool("i")
        assert td.routing_meta["requires_confirmation"] is True
        assert td.required_permissions == {"p"}


# ── Core enforcement parity (TASK-2580) ─────────────────────────────────────


class _AllowAllResolver(AbstractPermissionResolver):
    async def can_execute(self, context, tool_name, required_permissions):
        return True


class _DenyAllResolver(AbstractPermissionResolver):
    async def can_execute(self, context, tool_name, required_permissions):
        return False


class _BoomResolver(AbstractPermissionResolver):
    async def can_execute(self, context, tool_name, required_permissions):
        raise RuntimeError("resolver boom")


class _BlockGuardrail(Guardrail):
    name = "blocker"
    stages: ClassVar[set] = {GuardrailStage.TOOL_CALL}
    priority = 10
    on_error = "fail_closed"

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        return GuardrailResult(
            action=GuardrailAction.BLOCK,
            reason="policy:blocked",
            report={"message": "Denied by policy."},
        )


class _PassGuardrail(Guardrail):
    name = "pass_through"
    stages: ClassVar[set] = {GuardrailStage.TOOL_CALL}
    priority = 10
    on_error = "fail_closed"

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        return GuardrailResult(action=GuardrailAction.PASS)


class _RecordingAbstractTool(AbstractTool):
    """Minimal AbstractTool used to prove branch-parity/order preservation."""

    name = "recording_abstract_tool"
    description = "Records execution for order-preservation assertions."

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._exec_count = 0

    async def _execute(self, **kwargs) -> ToolResult:
        self._exec_count += 1
        return ToolResult(success=True, status="success", result="executed")


def _pipeline_with(*guardrails: Guardrail) -> GuardrailPipeline:
    pipeline = GuardrailPipeline()
    for g in guardrails:
        pipeline.add(g)
    return pipeline


class TestToolDefinitionEnforcement:
    """execute_tool() enforcement parity for the ToolDefinition branch
    (FEAT-474 G1/G4/G6/G7 — AC-1/AC-2/AC-3/AC-4/AC-5/AC-8/AC-9)."""

    @pytest.mark.asyncio
    async def test_resolver_denies_tooldef(self):
        tm = ToolManager(resolver=_DenyAllResolver())
        calls = []

        @tool
        def f(x: int) -> str:
            """Doc."""
            calls.append(x)
            return str(x)

        tm.register_tool(f)

        res = await tm.execute_tool("f", {"x": 1}, permission_context=object())
        assert res.status == "forbidden"
        assert calls == []

    @pytest.mark.asyncio
    async def test_fail_open_without_pctx(self):
        tm = ToolManager(resolver=_DenyAllResolver())

        @tool
        def g(x: int) -> str:
            """Doc."""
            return str(x)

        tm.register_tool(g)

        assert await tm.execute_tool("g", {"x": 2}) == "2"  # RAW value

    @pytest.mark.asyncio
    async def test_raw_return_on_allow(self):
        tm = ToolManager(resolver=_AllowAllResolver())

        @tool
        def h(x: int) -> str:
            """Doc."""
            return str(x)

        tm.register_tool(h)

        result = await tm.execute_tool("h", {"x": 3}, permission_context=object())
        assert result == "3"  # RAW value, not a ToolResult

    @pytest.mark.asyncio
    async def test_resolver_exception_propagates(self):
        tm = ToolManager(resolver=_BoomResolver())

        @tool
        def i(x: int) -> str:
            """Doc."""
            return str(x)

        tm.register_tool(i)

        with pytest.raises(RuntimeError, match="resolver boom"):
            await tm.execute_tool("i", {"x": 1}, permission_context=object())

    @pytest.mark.asyncio
    async def test_guardrail_blocks_tooldef(self):
        tm = ToolManager()
        tm._tool_call_pipeline = _pipeline_with(_BlockGuardrail())
        calls = []

        @tool
        def j(x: int) -> str:
            """Doc."""
            calls.append(x)
            return str(x)

        tm.register_tool(j)

        result = await tm.execute_tool("j", {"x": 1})
        assert isinstance(result, ToolResult)
        assert result.status == "forbidden"
        assert result.error == "Denied by policy."
        assert calls == []

    @pytest.mark.asyncio
    async def test_confirmation_cancelled_no_hitl(self):
        """requires_confirmation + no human_manager ⇒ fail-closed cancelled."""
        tm = ToolManager()
        guard = ConfirmationGuard(store=InMemoryConfirmationWindowStore())
        tm.set_confirmation_guard(guard)
        calls = []

        @tool(requires_confirmation=True)
        def k(x: int) -> str:
            """Doc."""
            calls.append(x)
            return str(x)

        tm.register_tool(k)

        result = await tm.execute_tool("k", {"x": 1})
        assert isinstance(result, ToolResult)
        assert result.status == "cancelled"
        assert calls == []

    @pytest.mark.asyncio
    async def test_no_confirmation_required_executes(self):
        """A @tool without requires_confirmation passes the guard untouched."""
        tm = ToolManager()
        guard = ConfirmationGuard(store=InMemoryConfirmationWindowStore())
        tm.set_confirmation_guard(guard)

        @tool
        def m(x: int) -> str:
            """Doc."""
            return str(x)

        tm.register_tool(m)

        assert await tm.execute_tool("m", {"x": 5}) == "5"

    @pytest.mark.asyncio
    async def test_abstracttool_order_unchanged(self):
        """AbstractTool branch order (pipeline -> grant -> confirm -> execute)
        is byte-for-byte preserved after hoisting the guardrail block."""
        from parrot.auth.confirmation import ConfirmationDecision
        from parrot.auth.grants import GuardDecision

        tm = ToolManager()
        rtool = _RecordingAbstractTool()
        tm._tools[rtool.name] = rtool
        tm._tool_call_pipeline = _pipeline_with(_PassGuardrail())

        call_order: list[str] = []

        class _OrderGrant:
            async def authorize(self, *, tool, parameters, permission_context=None):
                call_order.append("grant")
                return GuardDecision(allowed=True, reason="ok")

        class _OrderConfirm:
            async def confirm(self, *, tool, parameters, permission_context=None):
                call_order.append("confirm")
                return ConfirmationDecision(allowed=True, status="confirmed", reason="ok", parameters=parameters)

        original_run = tm._tool_call_pipeline.run

        async def _tracking_run(content, ctx):
            call_order.append("tool_call")
            return await original_run(content, ctx)

        tm._tool_call_pipeline.run = _tracking_run
        tm._grant_guard = _OrderGrant()
        tm._confirmation_guard = _OrderConfirm()

        await tm.execute_tool(rtool.name, {})

        assert call_order == ["tool_call", "grant", "confirm"]
        assert rtool._exec_count == 1

    @pytest.mark.asyncio
    async def test_enforcement_log_uniform(self, caplog):
        """Allow/deny decisions on both branches emit the shared structured
        record via ToolManager._log_enforcement() (FEAT-474 G6/AC-9)."""
        tm = ToolManager(resolver=_DenyAllResolver())

        @tool
        def n(x: int) -> str:
            """Doc."""
            return str(x)

        tm.register_tool(n)

        with caplog.at_level(logging.INFO):
            await tm.execute_tool("n", {"x": 1}, permission_context=object())

        records = [r.getMessage() for r in caplog.records]
        assert any("layer=resolver" in m and "decision=deny" in m and "kind=tool_definition" in m for m in records)

    @pytest.mark.asyncio
    async def test_enforcement_log_uniform_abstracttool_resolver_deny(self, caplog):
        """The AbstractTool branch's Layer 2 resolver denial (computed inside
        AbstractTool.execute(), abstract.py:875-890) is ALSO observed through
        the shared _log_enforcement() helper when execute_tool() sees the
        resulting forbidden ToolResult — closing the AC-9 asymmetry a
        code-review pass found between the two branches (the check itself
        intentionally stays inside AbstractTool; only the logging point
        moved to be uniform)."""

        class _GuardedAbstractTool(AbstractTool):
            name = "guarded_abstract_tool"
            description = "Requires admin."
            _required_permissions = frozenset({"admin"})

            async def _execute(self, **kwargs) -> ToolResult:
                return ToolResult(success=True, status="success", result="ok")

        tm = ToolManager(resolver=_DenyAllResolver())
        tm.add_tool(_GuardedAbstractTool())

        with caplog.at_level(logging.INFO):
            await tm.execute_tool(
                "guarded_abstract_tool",
                {},
                permission_context=SimpleNamespace(user_id="u-1"),
            )

        records = [r.getMessage() for r in caplog.records]
        assert any("layer=resolver" in m and "decision=deny" in m and "kind=abstract_tool" in m for m in records)
