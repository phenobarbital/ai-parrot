"""Unit tests for AbstractTool lifecycle event integration.

FEAT-176 — Lifecycle Events System (TASK-1195).

Uses minimal concrete subclasses of AbstractTool to verify Before/After/Failed
event emission and trace context wiring — without any real I/O or LLM calls.
"""
from __future__ import annotations

import asyncio

import pytest

from parrot.core.events.lifecycle.events import (
    BeforeToolCallEvent,
    AfterToolCallEvent,
    ToolCallFailedEvent,
)
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.auth.permission import PermissionContext, UserSession
from parrot.tools.abstract import AbstractTool, ToolResult


# ---------------------------------------------------------------------------
# Minimal concrete tool subclasses
# ---------------------------------------------------------------------------

class _OkTool(AbstractTool):
    """Tool that always succeeds and returns a ToolResult."""

    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(status="success", result="ok")


class _FailTool(AbstractTool):
    """Tool whose _execute() raises a ValueError."""

    async def _execute(self, **kwargs) -> ToolResult:
        raise ValueError("intentional failure")


def _make_pctx(trace_context: TraceContext | None = None) -> PermissionContext:
    """Build a minimal PermissionContext suitable for tests."""
    session = UserSession(
        user_id="test-user",
        tenant_id="test-tenant",
        roles=frozenset({"admin"}),
    )
    return PermissionContext(session=session, trace_context=trace_context)


def _capture():
    """Return (captured_list, async_callback)."""
    captured: list = []

    async def cb(event):
        captured.append(event)

    return captured, cb


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestToolLifecycle:
    """Verify lifecycle event emission from AbstractTool.execute()."""

    def test_abstract_tool_exposes_events(self) -> None:
        """AbstractTool exposes self.events (EventRegistry) after __init__."""
        tool = _OkTool(name="ok-tool")
        assert isinstance(tool.events, EventRegistry)

    @pytest.mark.asyncio
    async def test_success_emits_before_and_after(self) -> None:
        """Before + After are emitted on success; Failed is NOT."""
        tool = _OkTool(name="ok-tool")
        before_evts, before_cb = _capture()
        after_evts, after_cb = _capture()
        failed_evts, failed_cb = _capture()

        tool.events.subscribe(BeforeToolCallEvent, before_cb)
        tool.events.subscribe(AfterToolCallEvent, after_cb)
        tool.events.subscribe(ToolCallFailedEvent, failed_cb)

        result = await tool.execute(x="hello", y=42)

        # Give async emit tasks a chance to complete
        await asyncio.sleep(0)

        assert len(before_evts) == 1
        assert len(after_evts) == 1
        assert len(failed_evts) == 0

        assert isinstance(before_evts[0], BeforeToolCallEvent)
        assert isinstance(after_evts[0], AfterToolCallEvent)

        assert before_evts[0].tool_name == "ok-tool"
        assert after_evts[0].tool_name == "ok-tool"
        assert after_evts[0].duration_ms >= 0.0
        assert after_evts[0].result_status == "success"

        # Returned result should be ToolResult(status="success")
        assert isinstance(result, ToolResult)
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_failure_emits_failed_not_after(self) -> None:
        """On _execute() exception: Failed is emitted; After is NOT.

        Note: AbstractTool.execute() catches exceptions and returns
        ToolResult(status='error') rather than re-raising, so the test
        checks the returned result instead of expecting an exception.
        """
        tool = _FailTool(name="fail-tool")
        before_evts, before_cb = _capture()
        after_evts, after_cb = _capture()
        failed_evts, failed_cb = _capture()

        tool.events.subscribe(BeforeToolCallEvent, before_cb)
        tool.events.subscribe(AfterToolCallEvent, after_cb)
        tool.events.subscribe(ToolCallFailedEvent, failed_cb)

        result = await tool.execute()
        await asyncio.sleep(0)

        assert len(before_evts) == 1
        assert len(failed_evts) == 1
        assert len(after_evts) == 0  # After MUST NOT be emitted on failure

        assert failed_evts[0].error_type == "ValueError"
        assert "intentional failure" in failed_evts[0].error_message
        assert failed_evts[0].duration_ms >= 0.0

        # Result should be an error ToolResult (not a raised exception)
        assert isinstance(result, ToolResult)
        assert result.status == "error"

    @pytest.mark.asyncio
    async def test_trace_child_wiring(self) -> None:
        """BeforeToolCallEvent carries a child span of the parent trace."""
        parent_tc = TraceContext.new_root()
        pctx = _make_pctx(trace_context=parent_tc)

        tool = _OkTool(name="traced-tool")
        captured, cb = _capture()
        tool.events.subscribe(BeforeToolCallEvent, cb)

        await tool.execute(_permission_context=pctx)
        await asyncio.sleep(0)

        assert len(captured) >= 1
        evt = captured[0]
        # Child span shares trace_id with parent
        assert evt.trace_context.trace_id == parent_tc.trace_id
        # Child span references parent as its parent_span_id
        assert evt.trace_context.parent_span_id == parent_tc.span_id

    @pytest.mark.asyncio
    async def test_pctx_trace_updated_before_execute(self) -> None:
        """pctx.trace_context is updated to the tool's child span before _execute runs.

        This ensures sub-agents invoked inside the tool see the tool's span
        as their parent (A2A trace propagation).
        """
        parent_tc = TraceContext.new_root()
        pctx = _make_pctx(trace_context=parent_tc)

        tool = _OkTool(name="a2a-tool")
        await tool.execute(_permission_context=pctx)

        # After execute(), pctx.trace_context should be the tool's child span
        assert pctx.trace_context is not None
        assert pctx.trace_context.trace_id == parent_tc.trace_id
        assert pctx.trace_context.parent_span_id == parent_tc.span_id

    @pytest.mark.asyncio
    async def test_no_pctx_creates_root_trace(self) -> None:
        """When no _permission_context is given, a root TraceContext is minted."""
        tool = _OkTool(name="no-pctx-tool")
        captured, cb = _capture()
        tool.events.subscribe(BeforeToolCallEvent, cb)

        await tool.execute()
        await asyncio.sleep(0)

        assert len(captured) >= 1
        # Root span has no parent
        assert captured[0].trace_context.parent_span_id is None

    def test_args_summary_truncates_long_strings(self) -> None:
        """_args_summary truncates strings longer than 200 chars."""
        tool = _OkTool(name="t")
        long_str = "a" * 300
        summary = tool._args_summary({"prompt": long_str, "count": 5})

        assert len(summary["prompt"]) <= 202  # 200 chars + "…"
        assert summary["prompt"].endswith("…")
        assert summary["count"] == 5

    def test_args_summary_omits_private_keys(self) -> None:
        """_args_summary skips keys starting with underscore."""
        tool = _OkTool(name="t")
        summary = tool._args_summary({"_internal": "secret", "public": "visible"})
        assert "_internal" not in summary
        assert summary["public"] == "visible"

    def test_args_summary_handles_complex_types(self) -> None:
        """_args_summary replaces complex types with descriptors."""
        tool = _OkTool(name="t")
        summary = tool._args_summary({
            "items": [1, 2, 3],
            "data": {"key": "val"},
            "obj": object(),
        })
        assert summary["items"] == "<list len=3>"
        assert summary["data"] == "<dict len=1>"
        assert "<object>" in summary["obj"]

    def test_result_size_uses_result_field(self) -> None:
        """_result_size uses the 'result' attribute of ToolResult."""
        tool = _OkTool(name="t")
        tr = ToolResult(status="success", result="hello world")
        size = tool._result_size(tr)
        assert size > 0

    @pytest.mark.asyncio
    async def test_before_event_contains_args_summary(self) -> None:
        """BeforeToolCallEvent.args_summary reflects the tool arguments."""
        tool = _OkTool(name="summary-tool")
        captured, cb = _capture()
        tool.events.subscribe(BeforeToolCallEvent, cb)

        await tool.execute(message="test", count=3)
        await asyncio.sleep(0)

        assert len(captured) >= 1
        summary = captured[0].args_summary
        assert "message" in summary or "count" in summary  # at least one kwarg captured
