"""Unit tests for FEAT-536 TASK-2937/TASK-2938 — opt-in complete ToolResult
execution, output-field guard processing, and shared-instance isolation.

Adds ``ToolManager.execute_tool(..., return_tool_result=True)``: a
keyword-only, opt-in option. Default-mode (``return_tool_result=False``,
the default) behavior must remain byte-for-byte unchanged — these tests
exercise both branches side by side using real ``AbstractTool``/
``ToolkitTool``/``ToolDefinition`` tools and the real manager, mocking only
the guardrail/grant/confirmation/resolver stubs needed to observe
enforcement order and denial statuses (same pattern as
``test_tooldefinition_enforcement.py`` and ``test_toolmanager_confirmation.py``).

Test names below are the tasks' required target tests (§ Test
Specification, TASK-2937/TASK-2938); each is implemented as a class
grouping the scenarios that make up that behavioral guarantee.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, ClassVar

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


# ── TASK-2938 fixtures: voice/display output-guard processing ────────────


class _GuardedVoiceTool(AbstractTool):
    """Minimal AbstractTool isolating voice_text/display_data output-guard
    behavior. ``result``/``error``/``metadata`` are intentionally empty/
    None so ``AbstractTool.execute()``'s own (separate, pre-existing)
    result/error/metadata scrub gate never fires — keeping these fixtures'
    assertions about voice_text/display_data uncontaminated by that
    unrelated pipeline."""

    name = "guarded_voice_tool"
    description = "Returns only voice_text/display_data, for output-guard tests."

    def __init__(self, voice_text: str | None = None, display_data: dict | None = None, **kwargs):
        super().__init__(**kwargs)
        self._voice_text = voice_text
        self._display_data = display_data

    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            status="success",
            result=None,
            voice_text=self._voice_text,
            display_data=self._display_data,
        )


class _TransformVoiceGuardrail(Guardrail):
    name = "transform_voice"
    stages: ClassVar[set] = {GuardrailStage.TOOL_OUTPUT}
    priority = 50
    on_error = "fail_open"

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        return GuardrailResult(action=GuardrailAction.TRANSFORM, content=content.replace("SECRET-123", "[redacted]"))


class _BlockVoiceGuardrail(Guardrail):
    name = "block_voice"
    stages: ClassVar[set] = {GuardrailStage.TOOL_OUTPUT}
    priority = 10
    on_error = "fail_closed"

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        return GuardrailResult(action=GuardrailAction.BLOCK, reason="sensitive content")


class _FlagVoiceGuardrail(Guardrail):
    name = "flag_voice"
    stages: ClassVar[set] = {GuardrailStage.TOOL_OUTPUT}
    priority = 200
    on_error = "fail_open"

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        return GuardrailResult(action=GuardrailAction.FLAG, report={"note": "flagged"})


class _DisplayDataScrubGuardrail(Guardrail):
    """Non-str escape hatch (see ``GuardrailPipeline.guardrails`` docstring):
    redacts a ``"secret"`` key from dict payloads, preserving dict shape."""

    name = "display_scrub"
    stages: ClassVar[set] = {GuardrailStage.TOOL_OUTPUT}
    priority = 50
    on_error = "fail_open"

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        return GuardrailResult(action=GuardrailAction.PASS)  # never called for dict values

    def scrub(self, value: Any, tool_name: str | None = None) -> Any:
        if isinstance(value, dict):
            redacted = dict(value)
            redacted.pop("secret", None)
            return redacted
        return value


class _MalformedDisplayScrubGuardrail(Guardrail):
    """Simulates a misbehaving guardrail whose ``scrub()`` returns a
    non-dict on success (no exception) — must be suppressed, not forwarded."""

    name = "malformed_display_scrub"
    stages: ClassVar[set] = {GuardrailStage.TOOL_OUTPUT}
    priority = 50
    on_error = "fail_open"

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        return GuardrailResult(action=GuardrailAction.PASS)

    def scrub(self, value: Any, tool_name: str | None = None) -> Any:
        return "not-a-dict-anymore"


class _BoomDisplayScrubGuardrail(Guardrail):
    """``scrub()`` raises; ``on_error="fail_closed"`` — the existing
    ``_run_tool_output_guardrails()`` helper itself replaces the value with
    a safe placeholder dict (never the original sensitive value)."""

    name = "boom_display_scrub"
    stages: ClassVar[set] = {GuardrailStage.TOOL_OUTPUT}
    priority = 50
    on_error = "fail_closed"

    async def check(self, content: str, ctx: GuardrailContext) -> GuardrailResult:
        return GuardrailResult(action=GuardrailAction.PASS)

    def scrub(self, value: Any, tool_name: str | None = None) -> Any:
        raise RuntimeError("scrub boom")


class _BoomPipeline:
    """Duck-typed pipeline whose `.guardrails` property raises — used to
    prove a genuinely-raised processing exception is caught and suppressed
    by ``_finish_abstract_tool_full_result()``, not left to propagate with
    the original unsafe value forwarded."""

    has_guardrails = True

    @property
    def guardrails(self):
        raise RuntimeError("pipeline boom")


# ── test_full_result_output_fields_obey_guards ────────────────────────────


class TestFullResultOutputFieldsObeyGuards:
    """Transform/block/flag and processing-error fixtures prove no original
    sensitive voice/display field escapes when output guardrails/redaction
    are configured (FEAT-536 TASK-2938)."""

    @pytest.mark.asyncio
    async def test_voice_text_transform(self):
        tm = _tool_manager()
        tool_instance = _GuardedVoiceTool(voice_text="token=SECRET-123 please speak this")
        tm._tool_output_pipeline = _pipeline_with(_TransformVoiceGuardrail())
        tm.register_tool(tool_instance)

        result = await tm.execute_tool(tool_instance.name, {}, return_tool_result=True)

        assert "SECRET-123" not in result.voice_text
        assert "[redacted]" in result.voice_text

    @pytest.mark.asyncio
    async def test_voice_text_block_uses_safe_placeholder(self):
        tm = _tool_manager()
        tool_instance = _GuardedVoiceTool(voice_text="the sensitive number is 12345")
        tm._tool_output_pipeline = _pipeline_with(_BlockVoiceGuardrail())
        tm.register_tool(tool_instance)

        result = await tm.execute_tool(tool_instance.name, {}, return_tool_result=True)

        assert result.voice_text is not None  # a safe placeholder — still speakable
        assert "12345" not in result.voice_text
        assert "removed" in result.voice_text.lower()

    @pytest.mark.asyncio
    async def test_voice_text_flag_recorded_in_metadata(self):
        tm = _tool_manager()
        tool_instance = _GuardedVoiceTool(voice_text="ordinary text")
        tm._tool_output_pipeline = _pipeline_with(_FlagVoiceGuardrail())
        tm.register_tool(tool_instance)

        result = await tm.execute_tool(tool_instance.name, {}, return_tool_result=True)

        assert result.voice_text == "ordinary text"  # FLAG doesn't alter content
        assert result.metadata["guardrails"]["flag_voice"] == {"note": "flagged"}

    @pytest.mark.asyncio
    async def test_display_data_scrub_removes_secret_key(self):
        tm = _tool_manager()
        tool_instance = _GuardedVoiceTool(display_data={"secret": "sk-abc123", "chart": "bar"})
        tm._tool_output_pipeline = _pipeline_with(_DisplayDataScrubGuardrail())
        tm.register_tool(tool_instance)

        result = await tm.execute_tool(tool_instance.name, {}, return_tool_result=True)

        assert "secret" not in result.display_data
        assert result.display_data["chart"] == "bar"

    @pytest.mark.asyncio
    async def test_display_data_suppressed_when_no_longer_a_dict(self):
        tm = _tool_manager()
        tool_instance = _GuardedVoiceTool(display_data={"secret": "sk-abc123"})
        tm._tool_output_pipeline = _pipeline_with(_MalformedDisplayScrubGuardrail())
        tm.register_tool(tool_instance)

        result = await tm.execute_tool(tool_instance.name, {}, return_tool_result=True)

        assert result.display_data is None  # suppressed — never forwarded as a non-dict
        assert "sk-abc123" not in str(result.metadata)
        assert result.metadata["output_guard_errors"]["display_data"]

    @pytest.mark.asyncio
    async def test_display_data_fail_closed_scrub_error_never_leaks_original(self):
        tm = _tool_manager()
        original = {"secret": "sk-abc123", "chart": "bar"}
        tool_instance = _GuardedVoiceTool(display_data=dict(original))
        tm._tool_output_pipeline = _pipeline_with(_BoomDisplayScrubGuardrail())
        tm.register_tool(tool_instance)

        result = await tm.execute_tool(tool_instance.name, {}, return_tool_result=True)

        # `_run_tool_output_guardrails()`'s own fail_closed handling
        # replaces the value with a safe placeholder dict (still
        # dict-shaped, so this manager code forwards it as-is) — the
        # original sensitive value never escapes either way.
        assert result.display_data != original
        assert "sk-abc123" not in str(result.display_data)

    @pytest.mark.asyncio
    async def test_display_data_processing_exception_is_suppressed_not_leaked(self):
        tm = _tool_manager()
        tool_instance = _GuardedVoiceTool(display_data={"secret": "sk-abc123"})
        tm._tool_output_pipeline = _BoomPipeline()
        tm.register_tool(tool_instance)

        result = await tm.execute_tool(tool_instance.name, {}, return_tool_result=True)

        assert result.display_data is None
        assert "sk-abc123" not in str(result.metadata)
        assert "display_data" in result.metadata["output_guard_errors"]

    @pytest.mark.asyncio
    async def test_no_guard_configuration_leaves_fields_untouched(self):
        """No pipeline/no enable_redaction: matches AbstractTool.execute()'s
        own gate — voice_text/display_data pass through unprocessed."""
        tm = _tool_manager()
        tool_instance = _GuardedVoiceTool(voice_text="hello", display_data={"a": 1})
        tm.register_tool(tool_instance)

        result = await tm.execute_tool(tool_instance.name, {}, return_tool_result=True)

        assert result.voice_text == "hello"
        assert result.display_data == {"a": 1}


# ── test_full_result_shared_tool_context_isolation ────────────────────────


class _GatedTool(AbstractTool):
    """Blocks in ``_execute`` until ``gate`` is set; records the
    ``_current_pctx`` snapshot observed at each entry, and signals
    ``entered`` the instant it starts running — used to prove full-mode
    calls to the SAME instance serialize (never overlap inside
    ``_execute``) while calls to DIFFERENT instances do not contend."""

    name = "gated_tool"
    description = "Blocks on a gate; records entry pctx snapshots."

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()
        self.observed: list[Any] = []

    async def _execute(self, **kwargs) -> ToolResult:
        self.observed.append(self._current_pctx)
        self.entered.set()
        await self.gate.wait()
        return ToolResult(status="success", result="done")


class TestFullResultSharedToolContextIsolation:
    """Two cloned managers sharing one tool instance cannot overlap mutable
    permission/pipeline state; distinct tool instances run concurrently;
    cancellation releases the lock so a following invocation completes."""

    @pytest.mark.asyncio
    async def test_shared_instance_serializes_full_mode_calls(self):
        tm1 = _tool_manager()
        tool_instance = _GatedTool()
        tm1.register_tool(tool_instance)
        tm2 = tm1.clone()  # shares the SAME tool instance by reference

        # AbstractTool.execute() unconditionally reads `pctx.trace_context`
        # when a permission_context is supplied — a bare `object()` (fine
        # for the ToolDefinition-path tests above, which never reach
        # `tool.execute()`) would blow up here, so use a minimal stub.
        class _Ctx:
            trace_context = None

        ctx_a = _Ctx()
        ctx_b = _Ctx()

        task_a = asyncio.create_task(
            tm1.execute_tool("gated_tool", {}, permission_context=ctx_a, return_tool_result=True)
        )
        await asyncio.wait_for(tool_instance.entered.wait(), timeout=1)
        tool_instance.entered.clear()

        task_b = asyncio.create_task(
            tm2.execute_tool("gated_tool", {}, permission_context=ctx_b, return_tool_result=True)
        )
        # task_b must be waiting on the LOCK — not yet inside _execute —
        # while task_a is still mid-flight (blocked on the gate).
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(tool_instance.entered.wait(), timeout=0.2)
        assert tool_instance.observed == [ctx_a]  # only task_a has entered so far
        assert tool_instance._current_pctx is ctx_a  # not clobbered by task_b

        tool_instance.gate.set()
        result_a = await task_a
        assert result_a.status == "success"

        # Now that task_a released the lock, task_b can enter and complete.
        await asyncio.wait_for(tool_instance.entered.wait(), timeout=1)
        result_b = await task_b
        assert result_b.status == "success"
        assert tool_instance.observed == [ctx_a, ctx_b]

    @pytest.mark.asyncio
    async def test_different_instances_run_concurrently(self):
        tm = _tool_manager()
        tool_a = _GatedTool()
        tool_a.name = "gated_tool_a"
        tool_b = _GatedTool()
        tool_b.name = "gated_tool_b"
        tm.register_tool(tool_a)
        tm.register_tool(tool_b)

        task_a = asyncio.create_task(tm.execute_tool("gated_tool_a", {}, return_tool_result=True))
        task_b = asyncio.create_task(tm.execute_tool("gated_tool_b", {}, return_tool_result=True))

        # Both enter without waiting on each other — no cross-instance lock.
        await asyncio.wait_for(tool_a.entered.wait(), timeout=1)
        await asyncio.wait_for(tool_b.entered.wait(), timeout=1)

        tool_a.gate.set()
        tool_b.gate.set()
        result_a = await task_a
        result_b = await task_b
        assert result_a.status == "success"
        assert result_b.status == "success"

    @pytest.mark.asyncio
    async def test_cancellation_releases_lock_for_next_invocation(self):
        tm = _tool_manager()
        tool_instance = _GatedTool()
        tm.register_tool(tool_instance)

        task = asyncio.create_task(tm.execute_tool("gated_tool", {}, return_tool_result=True))
        await asyncio.wait_for(tool_instance.entered.wait(), timeout=1)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # A following full-mode call on the SAME instance must not
        # deadlock — the cancelled call's `finally` released the lock.
        tool_instance.entered.clear()
        tool_instance.gate.set()  # already set — the next call falls through
        result = await asyncio.wait_for(tm.execute_tool("gated_tool", {}, return_tool_result=True), timeout=2)
        assert result.status == "success"
        assert result.result == "done"
