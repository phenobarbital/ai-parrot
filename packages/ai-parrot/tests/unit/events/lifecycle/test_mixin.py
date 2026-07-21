"""Unit tests for EventEmitterMixin and EventRegistry.emit_nowait().

FEAT-176 — Lifecycle Events System (TASK-1189).
"""
from __future__ import annotations

import asyncio
import logging
import pytest

from navigator_eventbus.lifecycle.global_registry import scope
from navigator_eventbus.lifecycle.mixin import EventEmitterMixin
from navigator_eventbus.lifecycle.registry import EventRegistry
from parrot.core.events.lifecycle.events import BeforeInvokeEvent
from navigator_eventbus.lifecycle.trace import TraceContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Host(EventEmitterMixin):
    """Simple host that calls _init_events with passed kwargs."""

    def __init__(self, **kwargs: object) -> None:
        self._init_events(**kwargs)


class _NoInit(EventEmitterMixin):
    """Host that never calls _init_events — tests lazy fallback."""
    pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMixin:
    def test_init_creates_registry(self) -> None:
        """_init_events() creates an EventRegistry accessible via self.events."""
        h = _Host()
        assert isinstance(h.events, EventRegistry)

    def test_lazy_fallback(self) -> None:
        """Accessing self.events without _init_events() returns a default registry."""
        h = _NoInit()
        assert isinstance(h.events, EventRegistry)

    def test_lazy_fallback_returns_same_instance(self) -> None:
        """Repeated access to self.events without _init_events() returns the same registry."""
        h = _NoInit()
        r1 = h.events
        r2 = h.events
        assert r1 is r2

    def test_init_registry_identity(self) -> None:
        """self.events always returns the same EventRegistry instance after init."""
        h = _Host()
        assert h.events is h.events

    def test_forward_to_global_default_true(self) -> None:
        """Default _init_events() creates a registry with forward_to_global=True."""
        h = _Host()
        assert h.events._forward_to_global is True

    def test_forward_to_global_opt_out(self) -> None:
        """forward_to_global=False is respected."""
        h = _Host(forward_to_global=False)
        assert h.events._forward_to_global is False

    @pytest.mark.asyncio
    async def test_global_forwarding_default(self) -> None:
        """By default, emitting on self.events propagates to the global registry."""
        captured: list[BeforeInvokeEvent] = []

        async def cap(e: BeforeInvokeEvent) -> None:
            captured.append(e)

        with scope() as global_reg:
            global_reg.subscribe(BeforeInvokeEvent, cap)
            h = _Host()
            await h.events.emit(BeforeInvokeEvent(trace_context=TraceContext.new_root()))
            # Forwarding goes via create_task — drain the event loop.
            await asyncio.sleep(0)

        assert len(captured) == 1

    @pytest.mark.asyncio
    async def test_global_forwarding_disabled(self) -> None:
        """forward_to_global=False prevents events from reaching the global registry."""
        captured: list[BeforeInvokeEvent] = []

        async def cap(e: BeforeInvokeEvent) -> None:
            captured.append(e)

        with scope() as global_reg:
            global_reg.subscribe(BeforeInvokeEvent, cap)
            h = _Host(forward_to_global=False)
            await h.events.emit(BeforeInvokeEvent(trace_context=TraceContext.new_root()))
            await asyncio.sleep(0)

        assert len(captured) == 0

    @pytest.mark.asyncio
    async def test_emit_nowait_under_loop(self) -> None:
        """emit_nowait() under a running event loop schedules the event."""
        captured: list[BeforeInvokeEvent] = []

        async def cap(e: BeforeInvokeEvent) -> None:
            captured.append(e)

        reg = EventRegistry(forward_to_global=False)
        reg.subscribe(BeforeInvokeEvent, cap)
        reg.emit_nowait(BeforeInvokeEvent(trace_context=TraceContext.new_root()))
        await asyncio.sleep(0)   # let the scheduled task run
        assert len(captured) == 1

    def test_emit_nowait_no_loop_drops(self, caplog: pytest.LogCaptureFixture) -> None:
        """emit_nowait() outside a running loop logs at DEBUG and does not raise."""
        reg = EventRegistry(forward_to_global=False)
        with caplog.at_level(logging.DEBUG, logger="parrot.core.events.lifecycle.registry"):
            # Must not raise
            reg.emit_nowait(BeforeInvokeEvent(trace_context=TraceContext.new_root()))
        assert any("no running event loop" in r.message for r in caplog.records)

    def test_emit_nowait_no_loop_does_not_raise(self) -> None:
        """emit_nowait() outside a running loop returns None without raising."""
        reg = EventRegistry(forward_to_global=False)
        result = reg.emit_nowait(BeforeInvokeEvent(trace_context=TraceContext.new_root()))
        assert result is None
