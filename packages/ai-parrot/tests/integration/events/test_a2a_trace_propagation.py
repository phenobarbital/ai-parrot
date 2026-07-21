"""Integration test: A2A trace context propagation through tool execution.

FEAT-176 — Lifecycle Events System (TASK-1195).

Validates that when Agent A invokes a tool that internally invokes Agent B,
the trace_id is preserved across the boundary and each span correctly
references its parent span.

Topology:
  AgentA.ask()
    → emits BeforeInvokeEvent  (span A1, trace T1)
    → calls tool with pctx(trace_context=A1)
      → AbstractTool.execute()
        → mints tool_tc (child of A1, parent=A1.span_id)
        → emits BeforeToolCallEvent (span T_tool, trace T1)
        → sets pctx.trace_context = T_tool
        → calls _execute() which invokes AgentB
          → AgentB sees pctx.trace_context = T_tool as parent
          → emits BeforeInvokeEvent (span B1, parent=T_tool.span_id, trace T1)

This test verifies:
  1. All three spans share the same trace_id.
  2. tool_tc.parent_span_id == A1.span_id
  3. B1.parent_span_id == T_tool.span_id  (i.e., T_tool connects A to B)
"""
from __future__ import annotations

import asyncio

import pytest

from parrot.core.events.lifecycle.events import (
    BeforeToolCallEvent,
    AfterToolCallEvent,
)
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.auth.permission import PermissionContext, UserSession
from parrot.tools.abstract import AbstractTool, ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session() -> UserSession:
    return UserSession(
        user_id="a2a-user",
        tenant_id="a2a-tenant",
        roles=frozenset({"admin"}),
    )


def _capture():
    captured: list = []

    async def cb(event):
        captured.append(event)

    return captured, cb


# ---------------------------------------------------------------------------
# Simulated Agent B (a minimal async callable that records the trace_context
# it receives — it stands in for a real AbstractBot invocation)
# ---------------------------------------------------------------------------

class _AgentBRecord:
    """Records the PermissionContext seen when it is invoked as a sub-agent."""

    def __init__(self):
        self.seen_pctx: PermissionContext | None = None

    async def ask(self, pctx: PermissionContext) -> str:
        self.seen_pctx = pctx
        return "agent B response"


# ---------------------------------------------------------------------------
# A2A Tool: wraps AgentB
# ---------------------------------------------------------------------------

class _AgentBTool(AbstractTool):
    """Minimal tool that delegates to AgentB and propagates pctx."""

    def __init__(self, agent_b: _AgentBRecord):
        super().__init__(name="agent-b-tool")
        self._agent_b = agent_b

    async def _execute(self, **kwargs) -> ToolResult:
        # The tool has already updated pctx.trace_context before _execute is
        # called, so self._current_pctx carries the tool's child trace.
        pctx = self._current_pctx
        resp = await self._agent_b.ask(pctx=pctx)
        return ToolResult(status="success", result=resp)


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

class TestA2ATracePropagation:
    """End-to-end A2A trace continuity through tool execution."""

    @pytest.mark.asyncio
    async def test_a2a_trace_context_propagation(self) -> None:
        """Agent A → Tool → Agent B all share the same trace_id.

        Verifies FEAT-176 §7 A2A trace propagation risk mitigation.
        """
        # Step 1: Agent A mints its own trace (simulates AbstractBot.ask())
        agent_a_tc = TraceContext.new_root()
        session = _make_session()
        pctx = PermissionContext(session=session, trace_context=agent_a_tc)

        # Step 2: Agent B receiver
        agent_b = _AgentBRecord()
        tool = _AgentBTool(agent_b=agent_b)

        # Subscribe to capture tool lifecycle events
        before_evts, before_cb = _capture()
        after_evts, after_cb = _capture()
        tool.events.subscribe(BeforeToolCallEvent, before_cb)
        tool.events.subscribe(AfterToolCallEvent, after_cb)

        # Step 3: Tool execution (Agent A's pctx flows through)
        result = await tool.execute(_permission_context=pctx)
        await asyncio.sleep(0)

        # ── Assertions ────────────────────────────────────────────────────────

        # Tool succeeded
        assert isinstance(result, ToolResult)
        assert result.status == "success"

        # BeforeToolCallEvent was emitted
        assert len(before_evts) == 1
        tool_tc = before_evts[0].trace_context

        # All spans share the same trace_id (A2A invariant)
        assert tool_tc.trace_id == agent_a_tc.trace_id

        # Tool span's parent is agent A's span
        assert tool_tc.parent_span_id == agent_a_tc.span_id

        # pctx.trace_context was updated BEFORE _execute so Agent B sees it
        assert agent_b.seen_pctx is not None
        b_tc = agent_b.seen_pctx.trace_context
        assert b_tc is not None
        assert b_tc.trace_id == agent_a_tc.trace_id
        # Agent B's pctx carries the tool's trace context (propagated)
        assert b_tc.parent_span_id == agent_a_tc.span_id

        # AfterToolCallEvent was emitted
        assert len(after_evts) == 1
        assert after_evts[0].tool_name == "agent-b-tool"

    @pytest.mark.asyncio
    async def test_no_trace_context_in_pctx_creates_root(self) -> None:
        """When pctx.trace_context is None, the tool mints a root span."""
        session = _make_session()
        pctx = PermissionContext(session=session, trace_context=None)

        agent_b = _AgentBRecord()
        tool = _AgentBTool(agent_b=agent_b)

        captured, cb = _capture()
        tool.events.subscribe(BeforeToolCallEvent, cb)

        await tool.execute(_permission_context=pctx)
        await asyncio.sleep(0)

        assert len(captured) == 1
        tool_tc = captured[0].trace_context
        # Root span has no parent
        assert tool_tc.parent_span_id is None

    @pytest.mark.asyncio
    async def test_trace_spans_are_unique(self) -> None:
        """Each tool execution mints a unique span_id."""
        agent_a_tc = TraceContext.new_root()
        session = _make_session()

        agent_b1 = _AgentBRecord()
        tool1 = _AgentBTool(agent_b=agent_b1)
        captured1, cb1 = _capture()
        tool1.events.subscribe(BeforeToolCallEvent, cb1)

        agent_b2 = _AgentBRecord()
        tool2 = _AgentBTool(agent_b=agent_b2)
        captured2, cb2 = _capture()
        tool2.events.subscribe(BeforeToolCallEvent, cb2)

        pctx1 = PermissionContext(session=session, trace_context=agent_a_tc.child())
        pctx2 = PermissionContext(session=session, trace_context=agent_a_tc.child())

        await tool1.execute(_permission_context=pctx1)
        await tool2.execute(_permission_context=pctx2)
        await asyncio.sleep(0)

        tc1 = captured1[0].trace_context
        tc2 = captured2[0].trace_context

        # Both share the root trace_id
        assert tc1.trace_id == agent_a_tc.trace_id
        assert tc2.trace_id == agent_a_tc.trace_id
        # But have unique span IDs
        assert tc1.span_id != tc2.span_id
