"""Tests for parrot.core.events.lifecycle.turn_scope (FEAT-573 TASK-3402)."""
from __future__ import annotations

import asyncio

import pytest  # verified: tests/unit/tools/test_tool_lifecycle.py:12

from parrot.core.events.lifecycle import TURN_SCOPE, get_global_registry, in_turn_scope, scope, turn_scope
from parrot.core.events.lifecycle.events import AfterToolCallEvent, BeforeToolCallEvent  # verified: test_tool_lifecycle.py:14
from parrot.tools.abstract import AbstractTool, ToolResult  # verified: test_tool_lifecycle.py:22


class _OkTool(AbstractTool):
    async def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(status="success", result="ok")


def test_turn_scope_sets_and_resets() -> None:
    assert TURN_SCOPE.get(None) is None
    with turn_scope("t1"):
        assert TURN_SCOPE.get(None) == "t1"
        assert in_turn_scope("t1")(object()) is True   # type: ignore[arg-type]
        assert in_turn_scope("other")(object()) is False  # type: ignore[arg-type]
    assert TURN_SCOPE.get(None) is None


@pytest.mark.asyncio
async def test_turn_scope_predicate_survives_create_task() -> None:
    seen: list[bool] = []

    async def emitter() -> None:
        seen.append(in_turn_scope("t1")(object()))  # type: ignore[arg-type]

    with turn_scope("t1"):
        await asyncio.create_task(emitter())
    await asyncio.create_task(emitter())  # outside the scope
    assert seen == [True, False]


@pytest.mark.asyncio
async def test_real_tool_events_reach_scoped_global_subscriber() -> None:
    captured: list = []

    async def cb(event) -> None:
        captured.append(event)

    with scope() as reg:
        assert get_global_registry() is reg
        reg.subscribe(BeforeToolCallEvent, cb, where=in_turn_scope("t1"))
        reg.subscribe(AfterToolCallEvent, cb, where=in_turn_scope("t1"))
        tool = _OkTool(name="ok-tool")
        with turn_scope("t1"):
            await tool.execute()
        await asyncio.sleep(0); await asyncio.sleep(0)  # let create_task-scheduled dispatches run
        # Order, not just membership: BeforeToolCallEvent is emitted via emit_nowait
        # (one extra create_task hop for the tool-registry -> global-registry forward)
        # while AfterToolCallEvent is emitted via a directly-awaited emit() whose forward
        # is scheduled synchronously — so After's global dispatch can legitimately win the
        # race and land in `captured` before Before's. Assert membership/count, not order.
        assert sorted(type(e).__name__ for e in captured) == sorted(
            ["BeforeToolCallEvent", "AfterToolCallEvent"]
        )
        await tool.execute()  # no scope → filtered out
        await asyncio.sleep(0); await asyncio.sleep(0)
        assert len(captured) == 2
        # Both events from the same tool.execute() call share one TraceContext (tool_tc),
        # minted once in AbstractTool.execute() and reused for Before/After — spec §2
        # "call_id is the tool event's span_id" (tools/abstract.py:939, :948, :1132).
        # Look up by type rather than fixed index — arrival order is not guaranteed (see above).
        before_evt = next(e for e in captured[:2] if type(e).__name__ == "BeforeToolCallEvent")
        after_evt = next(e for e in captured[:2] if type(e).__name__ == "AfterToolCallEvent")
        assert before_evt.trace_context.span_id == after_evt.trace_context.span_id
