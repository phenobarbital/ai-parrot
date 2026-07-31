"""Unit tests for EventRegistry fire-and-forget bus dispatch.

FEAT-177 — TASK-1227. Validates that the per-subscriber ``forward_to_bus``
branch of :meth:`EventRegistry.emit` no longer blocks the agent request
path when the configured ``EventBus`` is slow or fails synchronously.

The spec (§5 Acceptance Criteria) requires:
  * A bus whose ``emit`` blocks on an ``asyncio.Event`` does NOT delay
    ``EventRegistry.emit`` past a 100 ms wall-clock budget.
  * A bus task that raises does not propagate to the ``emit`` caller; the
    agent flow continues uninterrupted.
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from parrot.core.events.lifecycle.events import BeforeInvokeEvent
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.trace import TraceContext


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _SlowBus:
    """Fake :class:`EventBus` whose ``emit`` blocks until ``gate`` is set."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.called = 0

    async def emit(self, channel: str, payload: dict) -> None:  # noqa: D401
        self.called += 1
        await self.gate.wait()


class _FailingBus:
    """Fake :class:`EventBus` whose ``emit`` raises synchronously."""

    def __init__(self) -> None:
        self.called = 0

    async def emit(self, channel: str, payload: dict) -> None:  # noqa: D401
        self.called += 1
        raise RuntimeError("simulated bus failure")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_bus_dispatch_is_fire_and_forget() -> None:
    """A blocking bus must NOT delay ``EventRegistry.emit``.

    The task is scheduled via ``asyncio.create_task`` and only completes
    after ``gate`` is released — the inline ``await emit(event)`` must
    return well before the 100 ms budget.
    """
    bus = _SlowBus()
    reg = EventRegistry(forward_to_global=False, event_bus=bus)

    async def subscriber(_evt: BeforeInvokeEvent) -> None:
        return None

    reg.subscribe(BeforeInvokeEvent, subscriber, forward_to_bus=True)

    event = BeforeInvokeEvent(
        trace_context=TraceContext.new_root(),
        agent_name="test",
        method="ask",
    )

    # If bus dispatch were blocking, this would deadlock on ``bus.gate``.
    await asyncio.wait_for(reg.emit(event), timeout=0.1)

    # Yield once so the freshly scheduled task gets a chance to run
    # (it will block on ``bus.gate`` and increment ``called``).
    await asyncio.sleep(0)
    assert bus.called == 1, "bus task should have been scheduled and started"

    # Release the gate and let the scheduled task drain so pytest doesn't
    # leak a pending task warning.
    bus.gate.set()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_emit_bus_exception_does_not_break_emit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A bus task that raises must not propagate to ``emit``'s caller."""
    bus = _FailingBus()
    reg = EventRegistry(forward_to_global=False, event_bus=bus)

    async def subscriber(_evt: BeforeInvokeEvent) -> None:
        return None

    reg.subscribe(BeforeInvokeEvent, subscriber, forward_to_bus=True)

    event = BeforeInvokeEvent(
        trace_context=TraceContext.new_root(),
        agent_name="test",
        method="ask",
    )

    # Must not raise — the failing task runs out-of-band.
    with caplog.at_level(logging.ERROR):
        await reg.emit(event)
        # Let the failing task run to completion. Asyncio's default
        # task-exception handler logs unhandled exceptions automatically.
        await asyncio.sleep(0)

    assert bus.called == 1, "failing bus task should have been scheduled"
