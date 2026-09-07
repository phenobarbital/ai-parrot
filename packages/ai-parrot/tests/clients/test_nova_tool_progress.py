"""Unit tests for FEAT-536 TASK-2940/2941 — coordinate provider events and
tool completion without stalls; bound deadlines/interruption/shutdown.

Replaces the "queue and flush on next non-tool event" model (FEAT-416
TASK-2148) with a coordinator that admits a fully-parsed contentEnd(TOOL)
call immediately (execution starts right away, as its own ``asyncio.Task``)
and races the next provider event against every in-flight tool task, so it
"wakes" on whichever completes first — a slow/stalled tool can no longer
block audio/interruption delivery, and a provider that never sends another
event still gets its tool result. TASK-2941 adds a named per-call deadline,
interruption-generation tracking (stale visual suppression), the 32/4
admission/concurrency bounds as patchable named constants, and bounded
cooperative cleanup.

Uses a real ``ToolManager`` + real ``AbstractTool`` fixtures throughout —
only the Bedrock SDK/transport thin wrappers (``_open_stream``/
``_send_event``/``_iter_events``/``_close_stream``) are mocked, matching
``test_nova_tool_result.py``/``test_nova_dual_output.py``'s existing
pattern. Event gates (``asyncio.Event``) and patched deadlines replace
timing-sensitive sleeps throughout, per the tasks' own Test Specifications.

Test names below are the tasks' required target tests (§ Test
Specification, TASK-2940/TASK-2941); each is implemented as a class
grouping the scenarios that make up that behavioral guarantee.
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
            await asyncio.wait_for(result_sent.wait(), timeout=5)
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
            await asyncio.wait_for(tool_entered.wait(), timeout=5)
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
        tm.register_tool(_GatedTool(name="slow_tool", gate=slow_gate, entered=slow_entered, result="slow-result"))
        tm.register_tool(_GatedTool(name="fast_tool", gate=fast_gate, entered=fast_entered, result="fast-result"))
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
            await asyncio.wait_for(slow_entered.wait(), timeout=5)
            await asyncio.wait_for(fast_entered.wait(), timeout=5)
            # Complete the FAST tool first — its result must be delivered
            # and correlated by its OWN id before the slow one, even
            # though the slow one was admitted first.
            fast_gate.set()
            await asyncio.wait_for(first_result_sent.wait(), timeout=5)
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


# ── test_stale_visual_after_barge_in_is_suppressed ────────────────────────


class _VisualGatedTool(AbstractTool):
    """Like ``_GatedTool`` but also returns ``display_data`` — used to
    prove a stale generation's visual is suppressed while its result/id
    remain auditable."""

    description = "Gated tool that also returns display_data."

    def __init__(self, name: str, gate: asyncio.Event, entered: asyncio.Event, **kwargs):
        super().__init__(name=name, **kwargs)
        self._gate = gate
        self._entered = entered

    async def _execute(self, **kwargs) -> ToolResult:
        self._entered.set()
        await self._gate.wait()
        return ToolResult(status="success", result="ok", display_data={"chart": "stale-or-not"})


class TestStaleVisualAfterBargeInIsSuppressed:
    """Barge-in marks in-flight/queued calls' generation stale; their
    late visual is suppressed but the tool result/id stay auditable."""

    @pytest.mark.asyncio
    async def test_stale_visual_after_barge_in_is_suppressed(self):
        tool_gate = asyncio.Event()
        tool_entered = asyncio.Event()
        tm = ToolManager(include_search_tool=False)
        tm.register_tool(_VisualGatedTool(name="visual_tool", gate=tool_gate, entered=tool_entered))
        client = _make_client(tm)

        async def fake_events():
            yield {"toolUse": {"toolUseId": "tu_1", "toolName": "visual_tool", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            # Wait for the call to actually be running, THEN barge-in —
            # this admits/starts it under generation 0, then bumps the
            # generation to 1 while it is still in flight.
            await asyncio.wait_for(tool_entered.wait(), timeout=5)
            yield {"textOutput": {"content": '{"interrupted":true}'}}
            tool_gate.set()
            yield {"completionEnd": {}}

        responses, _ = await _run(client, fake_events())

        deltas = _tool_deltas(responses)
        assert len(deltas) == 1
        delta = deltas[0]
        # Auditable: the tool result and id still reach the caller.
        assert delta.tool_calls[0].id == "tu_1"
        assert delta.tool_calls[0].result == {"output": "ok"}
        assert delta.tool_calls[0].error is None
        # Suppressed: no display_data on a stale-generation delta.
        assert "display_data" not in delta.metadata
        assert delta.metadata.get("stale_generation") is True

    @pytest.mark.asyncio
    async def test_non_stale_visual_survives_without_barge_in(self):
        """Control case: no barge-in — the visual is NOT suppressed."""
        tool_gate = asyncio.Event()
        tool_entered = asyncio.Event()
        tm = ToolManager(include_search_tool=False)
        tm.register_tool(_VisualGatedTool(name="visual_tool", gate=tool_gate, entered=tool_entered))
        client = _make_client(tm)

        async def fake_events():
            yield {"toolUse": {"toolUseId": "tu_1", "toolName": "visual_tool", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            await asyncio.wait_for(tool_entered.wait(), timeout=5)
            tool_gate.set()
            yield {"completionEnd": {}}

        responses, _ = await _run(client, fake_events())

        delta = _tool_deltas(responses)[0]
        assert delta.metadata.get("display_data") == {"chart": "stale-or-not"}
        assert "stale_generation" not in delta.metadata


# ── test_limits_timeout_disconnect_and_reconnect ──────────────────────────


class TestLimitsTimeoutDisconnectAndReconnect:
    """Queue expiry, tool timeout, EOF and idle reconnect are tested with
    patched deadlines — no timing-sensitive sleeps."""

    @pytest.mark.asyncio
    async def test_tool_call_deadline_expires_running_call(self):
        never_gate = asyncio.Event()  # never set — the tool would hang forever without a deadline
        entered = asyncio.Event()
        tm = ToolManager(include_search_tool=False)
        tm.register_tool(_GatedTool(name="hangs_forever", gate=never_gate, entered=entered))
        client = _make_client(tm)
        client._TOOL_CALL_DEADLINE_SECONDS = 0.05  # patched, tiny — spec-named constant

        async def fake_events():
            yield {"toolUse": {"toolUseId": "tu_1", "toolName": "hangs_forever", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            yield {"completionEnd": {}}

        responses, _ = await _run(client, fake_events())

        delta = _tool_deltas(responses)[0]
        assert delta.metadata["tool_status"] == "error"
        assert delta.tool_calls[0].error is not None
        assert "deadline" in delta.tool_calls[0].error.lower() or "timeout" in delta.tool_calls[0].error.lower()

    @pytest.mark.asyncio
    async def test_deadline_expires_while_still_queued(self):
        """A call still QUEUED (never started) when its deadline elapses
        expires without ever dispatching — deadline is measured from
        ADMISSION, including queue wait (spec §2).

        Deadline is captured ONCE, at admission — reassigning
        ``client._TOOL_CALL_DEADLINE_SECONDS`` afterwards does not
        retroactively change an already-admitted call's deadline. This
        gives "blocker" a generous deadline (so it is only ever released
        by the gate, never by its own timeout — avoiding a race between
        the two calls' near-simultaneous deadlines) while echo_tool, only
        admitted AFTER the constant is lowered, gets a tiny one that can
        safely be observed elapsing while it is still queued behind
        blocker.
        """
        blocker_gate = asyncio.Event()
        blocker_entered = asyncio.Event()
        tm = ToolManager(include_search_tool=False)
        tm.register_tool(_GatedTool(name="blocker", gate=blocker_gate, entered=blocker_entered))
        tm.register_tool(_EchoTool())
        client = _make_client(tm)
        client._TOOL_CALL_DEADLINE_SECONDS = 5.0  # blocker: never expires on its own

        async def fake_events():
            # Serial mode (default): "blocker" occupies the only slot.
            yield {"toolUse": {"toolUseId": "tu_blocker", "toolName": "blocker", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            await asyncio.wait_for(blocker_entered.wait(), timeout=5)
            client._TOOL_CALL_DEADLINE_SECONDS = 0.02  # now: echo_tool gets a tiny deadline
            yield {"toolUse": {"toolUseId": "tu_echo", "toolName": "echo_tool", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            # Let echo_tool's tiny deadline elapse WHILE STILL QUEUED —
            # blocker (generous deadline) still holds the only slot.
            await asyncio.sleep(0.1)
            blocker_gate.set()
            yield {"completionEnd": {}}

        responses, _ = await _run(client, fake_events())

        deltas = {tc.id: tc for r in responses for tc in r.tool_calls}
        assert deltas["tu_blocker"].error is None  # released via the gate, not its own deadline
        assert deltas["tu_echo"].error is not None
        assert "deadline" in deltas["tu_echo"].error.lower()

    @pytest.mark.asyncio
    async def test_admission_bound_rejects_excess_with_correlated_error(self):
        tm = ToolManager(include_search_tool=False)
        gate = asyncio.Event()
        entered1 = asyncio.Event()
        entered2 = asyncio.Event()
        tm.register_tool(_GatedTool(name="t1", gate=gate, entered=entered1))
        tm.register_tool(_GatedTool(name="t2", gate=gate, entered=entered2))
        client = _make_client(tm)
        client._MAX_UNFINISHED_TOOLS = 1  # patched — spec-named constant

        async def fake_events():
            yield {"toolUse": {"toolUseId": "tu_1", "toolName": "t1", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            yield {"toolUse": {"toolUseId": "tu_2", "toolName": "t2", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            gate.set()
            yield {"completionEnd": {}}

        responses, _ = await _run(client, fake_events())

        overloaded = [r for r in responses if r.metadata.get("tool_status") == "overloaded"]
        assert len(overloaded) == 1
        assert overloaded[0].tool_calls[0].id == "tu_2"

    @pytest.mark.asyncio
    async def test_stream_eof_cleans_up_without_replay(self):
        """The provider stream ends abruptly (EOF/fatal disconnect) while
        a tool is still running — cleanup cancels it, no crash, no result
        is ever replayed on a (nonexistent) new stream."""
        gate = asyncio.Event()
        entered = asyncio.Event()
        tm = ToolManager(include_search_tool=False)
        tm.register_tool(_GatedTool(name="slow_tool", gate=gate, entered=entered))
        client = _make_client(tm)

        async def fake_events():
            yield {"toolUse": {"toolUseId": "tu_1", "toolName": "slow_tool", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            await asyncio.wait_for(entered.wait(), timeout=5)
            # Stream simply ends here — no completionEnd, tool never
            # released. Coordinator must still finish cleanly.

        responses, _ = await _run(client, fake_events())

        # A completion is still yielded so callers are never left hanging.
        assert responses[-1].is_complete is True
        # The never-released tool never produced a streamed delta (it was
        # cancelled during cleanup, not settled) — no fabricated result.
        assert _tool_deltas(responses) == []

    @pytest.mark.asyncio
    async def test_reconnect_deadline_settles_admitted_work_first(self):
        """Approaching the connection-limit still settles admitted work
        (spec §2) before signalling reconnect_required — reusing
        TASK-2940's drain path, now cap-respecting (TASK-2941).

        The connection-limit check runs once per received provider event
        (see audio.py's own note on why this is not an independent
        wall-clock timer). A tiny (but nonzero) patched limit plus a
        short real sleep — bounded and deterministic, not a race — lets
        the limit genuinely elapse only AFTER echo_tool is admitted, so
        the settle-before-reconnect behavior is exercised rather than
        short-circuited before admission ever happens.
        """
        tm = ToolManager(include_search_tool=False)
        tm.register_tool(_EchoTool())
        client = _make_client(tm)
        client._CONNECTION_LIMIT_SECONDS = 0.02

        async def fake_events():
            yield {"toolUse": {"toolUseId": "tu_1", "toolName": "echo_tool", "content": "{}"}}
            yield {"contentEnd": {"type": "TOOL"}}
            await asyncio.sleep(0.05)  # let the tiny connection limit elapse
            yield {"textOutput": {"content": "should not be reached before reconnect"}}

        responses, _ = await _run(client, fake_events())

        # The admitted echo_tool call was settled (delivered) even though
        # the connection limit fired on the very next event.
        deltas = _tool_deltas(responses)
        assert len(deltas) == 1
        assert deltas[0].tool_calls[0].id == "tu_1"
        assert responses[-1].metadata.get("reconnect_required") is True
