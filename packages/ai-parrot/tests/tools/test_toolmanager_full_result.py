"""Unit tests for FEAT-536 TASK-2937 — opt-in complete ToolResult execution.

Adds ``ToolManager.execute_tool(..., return_tool_result=True)``: a
keyword-only, opt-in option. Default-mode (``return_tool_result=False``,
the default) behavior must remain byte-for-byte unchanged — these tests
exercise both branches side by side using real ``AbstractTool``/
``ToolkitTool``/``ToolDefinition`` tools and the real manager, mocking only
the guardrail/grant/confirmation/resolver stubs needed to observe
enforcement order and denial statuses (same pattern as
``test_tooldefinition_enforcement.py`` and ``test_toolmanager_confirmation.py``).

Test names below are the task's required target tests (§ Test
Specification, TASK-2937); each is implemented as a class grouping the
scenarios that make up that behavioral guarantee.
"""

from __future__ import annotations

import threading
from typing import ClassVar

import pytest

from parrot.auth.confirmation import (
    ConfirmationDecision,
    ConfirmationGuard,
    InMemoryConfirmationWindowStore,
)
from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.grants import GuardDecision
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
from parrot.tools.manager import ToolManager
from parrot.tools.toolkit import AbstractToolkit


# ── Shared fixtures/tools ────────────────────────────────────────────────

# Nulls (elided by MINIMAL json_compact) so compression is observable.
BULKY_PAYLOAD = {
    "a": 1,
    "b": None,
    "rows": [{"x": 1, "y": None} for _ in range(5)],
}


class _VoiceAwareTool(AbstractTool):
    """AbstractTool returning voice_text/display_data plus a bulky result
    so compression differences between the two fields are observable."""

    name = "voice_aware_tool"
    description = "Returns voice_text/display_data plus a bulky result."

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.captured: list[ToolResult] = []

    async def _execute(self, **kwargs) -> ToolResult:
        result = ToolResult(
            success=True,
            status="success",
            result=dict(BULKY_PAYLOAD),
            voice_text="Spoken answer.",
            display_data={"chart": "bar", "values": [1, 2, 3]},
            metadata={"tool_name": self.name},
        )
        # AbstractTool.execute() returns this exact object unchanged when
        # no redaction/output-guardrail pipeline is configured — capture it
        # so tests can assert the manager never mutates it.
        self.captured.append(result)
        return result


class _VoiceAwareToolkit(AbstractToolkit):
    """ToolkitTool route: same voice-aware envelope via a toolkit method."""

    async def voice_toolkit_method(self) -> ToolResult:
        """Return a voice-aware ToolResult."""
        return ToolResult(
            success=True,
            status="success",
            result=dict(BULKY_PAYLOAD),
            voice_text="Toolkit spoken answer.",
            display_data={"chart": "line"},
        )


class _ErrorTool(AbstractTool):
    name = "error_tool"
    description = "Always fails with status=error."

    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=False, status="error", result="raw-error-payload", error="boom")


class _AuthRequiredTool(AbstractTool):
    name = "auth_required_tool"
    description = "Raises AuthorizationRequired."

    async def _execute(self, **kwargs) -> ToolResult:
        raise AuthorizationRequired(
            self.name, "Please authorize.", auth_url="https://example.test/auth", provider="acme"
        )


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
        return GuardrailResult(action=GuardrailAction.BLOCK, reason="policy:blocked", report={"message": "Denied by policy."})


def _pipeline_with(*guardrails: Guardrail) -> GuardrailPipeline:
    pipeline = GuardrailPipeline()
    for g in guardrails:
        pipeline.add(g)
    return pipeline


def _tool_manager(**kwargs) -> ToolManager:
    return ToolManager(include_search_tool=False, **kwargs)


# ── test_default_result_contract_unchanged ──────────────────────────────


class TestDefaultResultContractUnchanged:
    """``return_tool_result`` defaults to False: raw returns, AbstractTool
    compression/hooks and failures match baseline (unaffected by this task)."""

    @pytest.mark.asyncio
    async def test_abstracttool_default_returns_reduced_payload(self):
        tm = _tool_manager()
        tm.register_tool(_VoiceAwareTool())

        out = await tm.execute_tool("voice_aware_tool", {})

        assert not isinstance(out, ToolResult)
        assert "b" not in out  # MINIMAL json_compact elides null keys
        assert out["a"] == 1

    @pytest.mark.asyncio
    async def test_tooldefinition_default_returns_raw_value(self):
        tm = _tool_manager()

        @tool
        def f(x: int) -> str:
            """Doc."""
            return str(x)

        tm.register_tool(f)

        assert await tm.execute_tool("f", {"x": 5}) == "5"

    @pytest.mark.asyncio
    async def test_error_tool_default_raises(self):
        tm = _tool_manager()
        tm.register_tool(_ErrorTool())

        with pytest.raises(ValueError, match="boom"):
            await tm.execute_tool("error_tool", {})

    @pytest.mark.asyncio
    async def test_resolver_denies_tooldef_default_unaffected(self):
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


# ── test_full_result_preserves_voice_display_and_status ─────────────────


class TestFullResultPreservesVoiceDisplayAndStatus:
    """Real AbstractTool/ToolkitTool and ToolDefinition tools retain their
    envelope fields; the returned envelope/metadata is a distinct object,
    never the tool-owned instance."""

    @pytest.mark.asyncio
    async def test_abstracttool_full_result(self):
        tm = _tool_manager()
        tool_instance = _VoiceAwareTool()
        tm.register_tool(tool_instance)

        result = await tm.execute_tool("voice_aware_tool", {}, return_tool_result=True)

        assert isinstance(result, ToolResult)
        assert result.status == "success"
        assert result.success is True
        assert result.voice_text == "Spoken answer."
        assert result.display_data == {"chart": "bar", "values": [1, 2, 3]}
        # result.result is the normal postprocessed/compressed payload —
        # voice_text/display_data are NOT compressed.
        assert "b" not in result.result
        assert result.result["a"] == 1

        # The tool-owned envelope (captured inside _execute) is untouched:
        # different object, its metadata unchanged, its `result` still has
        # the null-valued "b" key that compression would have elided.
        original = tool_instance.captured[0]
        assert result is not original
        assert result.metadata is not original.metadata
        assert "b" in original.result

    @pytest.mark.asyncio
    async def test_toolkittool_full_result(self):
        tm = _tool_manager()
        tm.register_toolkit(_VoiceAwareToolkit())
        toolkit_names = [name for name in tm._tools if "voice_toolkit_method" in name]
        assert toolkit_names, "toolkit tool not registered"

        result = await tm.execute_tool(toolkit_names[0], {}, return_tool_result=True)

        assert isinstance(result, ToolResult)
        assert result.voice_text == "Toolkit spoken answer."
        assert result.display_data == {"chart": "line"}
        assert "b" not in result.result

    @pytest.mark.asyncio
    async def test_tooldefinition_full_result_wraps_raw_value(self):
        tm = _tool_manager()

        @tool
        def f(x: int) -> str:
            """Doc."""
            return str(x)

        tm.register_tool(f)

        result = await tm.execute_tool("f", {"x": 5}, return_tool_result=True)

        assert isinstance(result, ToolResult)
        assert result.status == "success"
        assert result.result == "5"

    @pytest.mark.asyncio
    async def test_tooldefinition_full_result_preserves_returned_toolresult(self):
        tm = _tool_manager()

        @tool
        def g(x: int) -> ToolResult:
            """Doc."""
            return ToolResult(status="success", result=x, voice_text="spoken", display_data={"v": x})

        tm.register_tool(g)

        result = await tm.execute_tool("g", {"x": 7}, return_tool_result=True)

        assert isinstance(result, ToolResult)
        assert result.voice_text == "spoken"
        assert result.display_data == {"v": 7}
        # No AbstractTool compression pipeline is silently added to
        # plain-function execution — result is unchanged.
        assert result.result == 7

    @pytest.mark.asyncio
    async def test_tooldefinition_full_result_does_not_interpret_dict_as_envelope(self):
        """A plain business dict is NOT treated as an envelope merely
        because it happens to have similar keys."""
        tm = _tool_manager()

        @tool
        def h(x: int) -> dict:
            """Doc."""
            return {"status": "ok", "result": x}  # looks envelope-ish, isn't

        tm.register_tool(h)

        result = await tm.execute_tool("h", {"x": 9}, return_tool_result=True)

        assert isinstance(result, ToolResult)
        assert result.status == "success"  # normalized wrapper status
        assert result.result == {"status": "ok", "result": 9}  # dict preserved whole


# ── test_full_result_preserves_enforcement_order ─────────────────────────


class TestFullResultPreservesEnforcementOrder:
    """Configured guardrail → grant (where applicable) → confirmation →
    resolver/broker path; denied operations never execute — same order in
    full mode as in default mode."""

    @pytest.mark.asyncio
    async def test_guardrail_blocks_before_dispatch(self):
        tm = _tool_manager()
        tm._tool_call_pipeline = _pipeline_with(_BlockGuardrail())
        tool_instance = _VoiceAwareTool()
        tm.register_tool(tool_instance)

        result = await tm.execute_tool("voice_aware_tool", {}, return_tool_result=True)

        assert isinstance(result, ToolResult)
        assert result.status == "forbidden"
        assert result.error == "Denied by policy."
        assert tool_instance.captured == []  # never executed

    @pytest.mark.asyncio
    async def test_grant_then_confirm_order_full_mode(self):
        tm = _tool_manager()
        tool_instance = _VoiceAwareTool()
        tm.register_tool(tool_instance)

        call_order = []

        class _OrderTrackingGrantGuard:
            async def authorize(self, *, tool, parameters, permission_context=None):
                call_order.append("grant")
                return GuardDecision(allowed=True, reason="grant ok")

        class _OrderTrackingConfirmGuard:
            async def confirm(self, *, tool, parameters, permission_context=None):
                call_order.append("confirm")
                return ConfirmationDecision(allowed=True, status="confirmed", reason="ok", parameters=parameters)

        tm._grant_guard = _OrderTrackingGrantGuard()
        tm._confirmation_guard = _OrderTrackingConfirmGuard()

        result = await tm.execute_tool("voice_aware_tool", {}, return_tool_result=True)

        assert call_order == ["grant", "confirm"]
        assert isinstance(result, ToolResult)
        assert result.status == "success"
        assert len(tool_instance.captured) == 1  # executed exactly once

    @pytest.mark.asyncio
    async def test_grant_deny_skips_confirmation_and_execution(self):
        tm = _tool_manager()
        tool_instance = _VoiceAwareTool()
        tm.register_tool(tool_instance)

        confirm_calls = []

        class _DenyGrantGuard:
            async def authorize(self, *, tool, parameters, permission_context=None):
                return GuardDecision(allowed=False, reason="no grant")

        class _ShouldNotBeCalledConfirmGuard:
            async def confirm(self, *, tool, parameters, permission_context=None):
                confirm_calls.append(1)
                return ConfirmationDecision(allowed=True, status="confirmed", reason="ok", parameters=parameters)

        tm._grant_guard = _DenyGrantGuard()
        tm._confirmation_guard = _ShouldNotBeCalledConfirmGuard()

        result = await tm.execute_tool("voice_aware_tool", {}, return_tool_result=True)

        assert isinstance(result, ToolResult)
        assert result.status == "forbidden"
        assert confirm_calls == []
        assert tool_instance.captured == []

    @pytest.mark.asyncio
    async def test_resolver_denies_tooldef_full_mode(self):
        tm = ToolManager(resolver=_DenyAllResolver())
        calls = []

        @tool
        def f(x: int) -> str:
            """Doc."""
            calls.append(x)
            return str(x)

        tm.register_tool(f)

        result = await tm.execute_tool("f", {"x": 1}, permission_context=object(), return_tool_result=True)

        assert isinstance(result, ToolResult)
        assert result.status == "forbidden"
        assert calls == []

    @pytest.mark.asyncio
    async def test_resolver_allows_tooldef_full_mode(self):
        tm = ToolManager(resolver=_AllowAllResolver())

        @tool
        def h(x: int) -> str:
            """Doc."""
            return str(x)

        tm.register_tool(h)

        result = await tm.execute_tool("h", {"x": 3}, permission_context=object(), return_tool_result=True)

        assert isinstance(result, ToolResult)
        assert result.status == "success"
        assert result.result == "3"


# ── test_full_result_error_and_auth_statuses ──────────────────────────────


class TestFullResultErrorAndAuthStatuses:
    """Error, forbidden, pending, authorization-required and unknown-tool
    states remain non-success in full mode; resolver exceptions propagate."""

    @pytest.mark.asyncio
    async def test_error_status_returned_not_raised(self):
        tm = _tool_manager()
        tm.register_tool(_ErrorTool())

        result = await tm.execute_tool("error_tool", {}, return_tool_result=True)

        assert isinstance(result, ToolResult)
        assert result.status == "error"
        assert result.success is False
        assert result.error == "boom"
        assert result.result == "raw-error-payload"  # NOT reduced/compressed

    @pytest.mark.asyncio
    async def test_unknown_tool_not_found(self):
        tm = _tool_manager()

        result = await tm.execute_tool("does_not_exist", {}, return_tool_result=True)

        assert isinstance(result, ToolResult)
        assert result.status == "not_found"
        assert result.success is False

    @pytest.mark.asyncio
    async def test_authorization_required_converted_to_toolresult(self):
        tm = _tool_manager()
        tm.register_tool(_AuthRequiredTool())

        result = await tm.execute_tool("auth_required_tool", {}, return_tool_result=True)

        assert isinstance(result, ToolResult)
        assert result.status == "authorization_required"
        assert result.metadata["provider"] == "acme"
        assert result.metadata["auth_url"] == "https://example.test/auth"

    @pytest.mark.asyncio
    async def test_confirmation_cancelled_returned_not_success(self):
        tm = _tool_manager()
        tool_instance = _VoiceAwareTool()
        tm.register_tool(tool_instance)

        class _CancellingConfirmGuard:
            async def confirm(self, *, tool, parameters, permission_context=None):
                return ConfirmationDecision(allowed=False, status="cancelled", reason="user said no")

        tm._confirmation_guard = _CancellingConfirmGuard()

        result = await tm.execute_tool("voice_aware_tool", {}, return_tool_result=True)

        assert isinstance(result, ToolResult)
        assert result.status == "cancelled"
        assert result.success is False
        assert tool_instance.captured == []

    @pytest.mark.asyncio
    async def test_resolver_exception_propagates_full_mode(self):
        tm = ToolManager(resolver=_BoomResolver())

        @tool
        def i(x: int) -> str:
            """Doc."""
            return str(x)

        tm.register_tool(i)

        with pytest.raises(RuntimeError, match="resolver boom"):
            await tm.execute_tool("i", {"x": 1}, permission_context=object(), return_tool_result=True)


# ── test_full_result_hooks_once_before_compression ────────────────────────


class TestFullResultHooksOnceBeforeCompression:
    """Original result observed exactly once by hooks, payload compressed
    normally, spoken/visual fields not compressed; sync full-mode functions
    do not block an independent event-loop probe."""

    @pytest.mark.asyncio
    async def test_hook_observes_original_payload_once(self):
        tm = _tool_manager()
        tool_instance = _VoiceAwareTool()
        tm.register_tool(tool_instance)

        seen = []
        tm.add_result_hook(lambda name, result, meta: seen.append((result, meta)))

        result = await tm.execute_tool("voice_aware_tool", {}, return_tool_result=True)

        assert len(seen) == 1  # hook ran exactly once
        seen_result, seen_meta = seen[0]
        assert seen_result == BULKY_PAYLOAD  # hook saw the pre-compression payload
        assert "b" in seen_result  # untouched by compression
        assert "b" not in result.result  # caller got the compressed payload
        # The hook's metadata dict is the SAME copy the manager built (not
        # the tool-owned instance's) — mutating it must not leak back.
        seen_meta["hook_marker"] = True
        assert result.metadata.get("hook_marker") is True  # same dict, aliased forward
        original = tool_instance.captured[0]
        assert "hook_marker" not in original.metadata  # tool-owned envelope untouched

    @pytest.mark.asyncio
    async def test_failed_operation_does_not_run_success_hooks(self):
        tm = _tool_manager()
        tm.register_tool(_ErrorTool())

        seen = []
        tm.add_result_hook(lambda name, result, meta: seen.append(result))

        result = await tm.execute_tool("error_tool", {}, return_tool_result=True)

        assert result.status == "error"
        assert seen == []  # no success hook run for a rejected/failed operation

    @pytest.mark.asyncio
    async def test_sync_full_mode_function_does_not_block_event_loop(self):
        tm = _tool_manager()

        started = threading.Event()
        release = threading.Event()
        thread_ids: dict[str, int] = {}

        @tool
        def blocking(x: int) -> str:
            """Doc."""
            thread_ids["tool"] = threading.get_ident()
            started.set()
            release.wait(timeout=5)
            return str(x)

        tm.register_tool(blocking)
        thread_ids["test"] = threading.get_ident()

        import asyncio

        task = asyncio.create_task(tm.execute_tool("blocking", {"x": 1}, return_tool_result=True))

        # The event loop remains free to run other coroutines while the
        # synchronous function blocks in its own thread (asyncio.to_thread).
        await asyncio.wait_for(asyncio.to_thread(started.wait, 5), timeout=5)
        probe_ran = []
        await asyncio.sleep(0)
        probe_ran.append(True)
        release.set()

        result = await task

        assert probe_ran == [True]
        assert isinstance(result, ToolResult)
        assert result.result == "1"
        assert thread_ids["tool"] != thread_ids["test"]  # ran off the event loop thread
