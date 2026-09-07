"""Unit tests for FEAT-536 TASK-2940 — coordinate provider events and tool
completion without stalls.

Replaces the "queue and flush on next non-tool event" model (FEAT-416
TASK-2148) with a coordinator that admits a fully-parsed contentEnd(TOOL)
call immediately (execution starts right away, as its own ``asyncio.Task``)
and races the next provider event against every in-flight tool task, so it
"wakes" on whichever completes first — a slow/stalled tool can no longer
block audio/interruption delivery, and a provider that never sends another
event still gets its tool result.

Uses a real ``ToolManager`` + real ``AbstractTool`` fixtures throughout —
only the Bedrock SDK/transport thin wrappers (``_open_stream``/
``_send_event``/``_iter_events``/``_close_stream``) are mocked, matching
``test_nova_tool_result.py``/``test_nova_dual_output.py``'s existing
pattern. Event gates (``asyncio.Event``) replace timing-sensitive sleeps
throughout, per the task's own Test Specification.

Test names below are the task's required target tests (§ Test
Specification, TASK-2940); each is implemented as a class grouping the
scenarios that make up that behavioral guarantee.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.clients.amazon.nova import NovaClient
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager


# ── Shared fixtures ────────────────────────────────────────────────────────


class _EchoTool(AbstractTool):
    """Returns immediately; records how many times it actually executed —
    the sharpest possible probe for "never re-executed" (spec §2)."""

    name = "echo_tool"
    description = "Returns immediately, counting invocations."

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.call_count = 0

    async def _execute(self, **kwargs) -> ToolResult:
        self.call_count += 1
        return ToolResult(status="success", result=f"call-{self.call_count}")


class _GatedTool(AbstractTool):
    """Blocks in ``_execute`` until an external gate is set; sets
    ``entered`` the instant it starts running. Used to prove other events
    (audio, interruption, another tool's completion) are delivered WHILE
    this one is still executing — never blocked behind it."""

    description = "Gated test tool — blocks until released."

    def __init__(self, name: str, gate: asyncio.Event, entered: asyncio.Event, result: str = "done", **kwargs):
        super().__init__(name=name, **kwargs)
        self._gate = gate
        self._entered = entered
        self._result = result

    async def _execute(self, **kwargs) -> ToolResult:
        self._entered.set()
        await self._gate.wait()
        return ToolResult(status="success", result=self._result)


def _make_client(tool_manager: ToolManager) -> NovaClient:
    with patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}):
        client = NovaClient(model="nova-2-sonic", region="us-east-1")
    client.tool_manager = tool_manager
    return client


async def _run(client, frames, on_send=None, **stream_voice_kwargs):
    """Drive ``stream_voice()`` with an async-generator/iterable of already-
    unwrapped provider frames, capturing every sent wire event.

    ``on_send`` (optional) is awaited with each event AFTER it is
    recorded — used to set gate ``asyncio.Event``s from inside the fake
    provider generator so tests can causally react to what the
    coordinator actually sent, instead of relying on fixed sleeps.
    """
    sent_events: list = []

    async def capture(_stream, event):
        sent_events.append(event)
        if on_send is not None:
            await on_send(event)

    async def audio():
        yield b"\x00\x01" * 8
        yield None

    with (
        patch.dict(sys.modules, {"aws_sdk_bedrock_runtime": MagicMock()}),
        patch.object(client, "_open_stream", return_value=AsyncMock()),
        patch.object(client, "_send_event", new=capture),
        patch.object(client, "_iter_events", return_value=frames),
        patch.object(client, "_close_stream", new=AsyncMock()),
    ):
        responses = [r async for r in client.stream_voice(audio(), **stream_voice_kwargs)]
    return responses, sent_events


def _tool_deltas(responses):
    """Streamed per-call deltas — tool_calls present, not the final snapshot."""
    return [r for r in responses if r.tool_calls and not r.is_complete]


def _final_snapshot(responses):
    return next(r for r in responses if r.is_complete and r.tool_calls)


# ── test_tool_result_without_next_provider_event ──────────────────────────


class TestToolResultWithoutNextProviderEvent:
    """A causally-gated fake provider obtains a matching tool result after
    TOOL-end WITHOUT supplying another provider event."""

    @pytest.mark.asyncio
    async def test_tool_result_without_next_provider_event(self):
        tm = ToolManager(include_search_tool=False)
        tm.register_tool(_EchoTool())
        client = _make_client(tm)

        result_sent = asyncio.Event()

        async def on_send(event):
            if "toolResult" in event.get("event", {}):
                result_sent.set()

        async def fake_events():
            yield {"toolUse": {"toolUseId": "tu_1", "toolName": "echo_tool", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            # Causal gate: the fake provider will NOT send completionEnd
            # until it has actually observed the tool result go out —
            # proving the coordinator delivered it without needing
            # another provider event to trigger the flush (the exact
            # progress risk FEAT-416's old "flush on next non-tool event"
            # model had).
            await asyncio.wait_for(result_sent.wait(), timeout=2)
            yield {"completionEnd": {}}

        responses, sent = await _run(client, fake_events())

        assert any("toolResult" in e.get("event", {}) for e in sent)
        deltas = _tool_deltas(responses)
        assert len(deltas) == 1
        assert deltas[0].tool_calls[0].result == {"output": "call-1"}
        assert deltas[0].tool_calls[0].id == "tu_1"


# ── test_audio_and_interruption_during_slow_tool ──────────────────────────


class TestAudioAndInterruptionDuringSlowTool:
    """A slow/incomplete tool does not prevent audio or barge-in delivery
    — both arrive while the tool is still executing."""

    @pytest.mark.asyncio
    async def test_audio_and_interruption_during_slow_tool(self):
        tool_gate = asyncio.Event()
        tool_entered = asyncio.Event()
        tm = ToolManager(include_search_tool=False)
        tm.register_tool(_GatedTool(name="slow_tool", gate=tool_gate, entered=tool_entered))
        client = _make_client(tm)

        async def fake_events():
            yield {"toolUse": {"toolUseId": "tu_1", "toolName": "slow_tool", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            # The tool is admitted and starts executing immediately —
            # wait for it to actually enter before sending audio/
            # interruption, so this genuinely proves they are delivered
            # WHILE it is still running (not merely before admission).
            await asyncio.wait_for(tool_entered.wait(), timeout=2)
            yield {"audioOutput": {"content": "AQI="}}  # base64 of b"\x01\x02"
            yield {"textOutput": {"content": '{"interrupted":true}'}}
            tool_gate.set()
            yield {"completionEnd": {}}

        responses, _ = await _run(client, fake_events())

        audio_idx = next(i for i, r in enumerate(responses) if r.audio_data)
        interrupt_idx = next(i for i, r in enumerate(responses) if r.is_interrupted)
        tool_idx = next(i for i, r in enumerate(responses) if r.tool_calls and not r.is_complete)

        assert audio_idx < tool_idx
        assert interrupt_idx < tool_idx


# ── test_parallel_completion_correlates_ids ───────────────────────────────


class TestParallelCompletionCorrelatesIds:
    """Two tools finish out of order; results and visuals associate with
    their IDs exactly once, and the final snapshot preserves ARRIVAL
    order regardless of completion order."""

    @pytest.mark.asyncio
    async def test_parallel_completion_correlates_ids(self):
        slow_gate = asyncio.Event()
        fast_gate = asyncio.Event()
        slow_entered = asyncio.Event()
        fast_entered = asyncio.Event()
        first_result_sent = asyncio.Event()

        tm = ToolManager(include_search_tool=False)
        tm.register_tool(
            _GatedTool(name="slow_tool", gate=slow_gate, entered=slow_entered, result="slow-result")
        )
        tm.register_tool(
            _GatedTool(name="fast_tool", gate=fast_gate, entered=fast_entered, result="fast-result")
        )
        client = _make_client(tm)

        async def on_send(event):
            if "toolResult" in event.get("event", {}):
                first_result_sent.set()

        async def fake_events():
            # Admit the SLOW tool first (arrival order), then the FAST one.
            yield {"toolUse": {"toolUseId": "tu_slow", "toolName": "slow_tool", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            yield {"toolUse": {"toolUseId": "tu_fast", "toolName": "fast_tool", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            await asyncio.wait_for(slow_entered.wait(), timeout=2)
            await asyncio.wait_for(fast_entered.wait(), timeout=2)
            # Complete the FAST tool first — its result must be delivered
            # and correlated by its OWN id before the slow one, even
            # though the slow one was admitted first.
            fast_gate.set()
            await asyncio.wait_for(first_result_sent.wait(), timeout=2)
            slow_gate.set()
            yield {"completionEnd": {}}

        responses, _ = await _run(client, fake_events(), on_send=on_send, parallel_tool_execution=True)

        deltas = _tool_deltas(responses)
        assert len(deltas) == 2
        assert deltas[0].tool_calls[0].id == "tu_fast"  # completed first
        assert deltas[0].tool_calls[0].result == {"output": "fast-result"}
        assert deltas[1].tool_calls[0].id == "tu_slow"
        assert deltas[1].tool_calls[0].result == {"output": "slow-result"}

        # Final snapshot preserves ARRIVAL order regardless of completion
        # order (spec §2: "Arrival order remains available for the final
        # snapshot").
        final = _final_snapshot(responses)
        assert [tc.id for tc in final.tool_calls] == ["tu_slow", "tu_fast"]


# ── test_sequential_and_same_instance_execution ───────────────────────────


class TestSequentialAndSameInstanceExecution:
    """Default serial order is respected; full-mode same-instance lock
    (TASK-2938) is respected even when parallel_tool_execution=True."""

    @pytest.mark.asyncio
    async def test_default_serial_order_single_running_at_a_time(self):
        order: list[str] = []

        class _OrderTrackingTool(AbstractTool):
            name = "order_tool"
            description = "Records start/end order."

            async def _execute(self, **kwargs) -> ToolResult:
                order.append(f"start:{kwargs.get('marker', '')}")
                await asyncio.sleep(0)
                order.append(f"end:{kwargs.get('marker', '')}")
                return ToolResult(status="success", result="ok")

        tm = ToolManager(include_search_tool=False)
        tm.register_tool(_OrderTrackingTool())
        client = _make_client(tm)

        async def fake_events():
            yield {"toolUse": {"toolUseId": "tu_1", "toolName": "order_tool", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            yield {"toolUse": {"toolUseId": "tu_2", "toolName": "order_tool", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            yield {"completionEnd": {}}

        # parallel_tool_execution defaults to False — at most one call runs
        # at a time regardless of how many are admitted back-to-back.
        responses, _ = await _run(client, fake_events())

        assert len(order) == 4
        # Contiguous start/end pairs — never interleaved.
        assert order[0].startswith("start:") and order[1].startswith("end:")
        assert order[2].startswith("start:") and order[3].startswith("end:")
        assert len(_tool_deltas(responses)) == 2

    @pytest.mark.asyncio
    async def test_same_instance_lock_respected_in_parallel_mode(self):
        """Two calls to the SAME AbstractTool instance never overlap
        inside _execute(), even with parallel_tool_execution=True — the
        manager's own per-instance lock (TASK-2938) serializes them; Nova's
        coordinator does not need to track instance identity itself."""
        order: list[str] = []

        class _OrderTrackingTool(AbstractTool):
            name = "shared_order_tool"
            description = "Records start/end order."

            async def _execute(self, **kwargs) -> ToolResult:
                order.append("start")
                await asyncio.sleep(0)
                order.append("end")
                return ToolResult(status="success", result="ok")

        tm = ToolManager(include_search_tool=False)
        tm.register_tool(_OrderTrackingTool())  # ONE shared instance
        client = _make_client(tm)

        async def fake_events():
            yield {"toolUse": {"toolUseId": "tu_1", "toolName": "shared_order_tool", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            yield {"toolUse": {"toolUseId": "tu_2", "toolName": "shared_order_tool", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            yield {"completionEnd": {}}

        responses, _ = await _run(client, fake_events(), parallel_tool_execution=True)

        # Even with Nova's own concurrency cap raised (parallel_tool_
        # execution=True admits both immediately as separate tasks), the
        # SAME tool instance never overlaps — never ["start", "start", ...].
        assert order == ["start", "end", "start", "end"]
        assert len(_tool_deltas(responses)) == 2


# ── test_duplicate_tool_completion_and_final_snapshot ─────────────────────


class TestDuplicateToolCompletionAndFinalSnapshot:
    """No re-execution on a duplicate contentEnd(TOOL) for an already-
    admitted id; the final snapshot does not duplicate relayed frames."""

    @pytest.mark.asyncio
    async def test_duplicate_tool_completion_and_final_snapshot(self):
        tm = ToolManager(include_search_tool=False)
        tool_instance = _EchoTool()
        tm.register_tool(tool_instance)
        client = _make_client(tm)

        async def fake_events():
            yield {"toolUse": {"toolUseId": "tu_dup", "toolName": "echo_tool", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            # A second toolUse/contentEnd(TOOL) pair REUSING the same
            # toolUseId — Nova would only do this on a genuine protocol
            # anomaly, but the coordinator must still not re-execute it.
            yield {"toolUse": {"toolUseId": "tu_dup", "toolName": "echo_tool", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            yield {"completionEnd": {}}

        responses, _ = await _run(client, fake_events())

        assert tool_instance.call_count == 1  # never re-executed
        deltas = _tool_deltas(responses)
        assert len(deltas) == 1  # only one streamed delta

        final = _final_snapshot(responses)
        assert len(final.tool_calls) == 1  # final snapshot does not duplicate
        assert final.tool_calls[0].id == "tu_dup"

    @pytest.mark.asyncio
    async def test_content_end_without_stashed_tool_use_is_ignored(self):
        """A contentEnd(TOOL) with no preceding toolUse (nothing to
        correlate it to) is dropped, not executed — spec §2 "Reject
        malformed or uncorrelatable input"."""
        tm = ToolManager(include_search_tool=False)
        tool_instance = _EchoTool()
        tm.register_tool(tool_instance)
        client = _make_client(tm)

        async def fake_events():
            yield {"contentEnd": {"type": "TOOL"}}  # no toolUse before this
            yield {"completionEnd": {}}

        responses, _ = await _run(client, fake_events())

        assert tool_instance.call_count == 0
        assert _tool_deltas(responses) == []
        assert responses[-1].is_complete is True
