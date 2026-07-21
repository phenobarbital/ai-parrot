"""Unit tests for EventRegistry — dispatch, ordering, error isolation, dual-emit.

FEAT-176 — Lifecycle Events System (TASK-1186).
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from navigator_eventbus.lifecycle.registry import EventRegistry, _emitting_meta
from navigator_eventbus.lifecycle.trace import TraceContext
from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.meta import SubscriberErrorEvent
from parrot.core.events.lifecycle.events import (
    BeforeInvokeEvent,
    AfterInvokeEvent,
    InvokeFailedEvent,
    BeforeToolCallEvent,
    AfterToolCallEvent,
    ClientStreamChunkEvent,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry() -> EventRegistry:
    """Isolated EventRegistry with global forwarding disabled."""
    return EventRegistry(forward_to_global=False)


@pytest.fixture
def trace_root() -> TraceContext:
    """Fresh root TraceContext."""
    return TraceContext.new_root()


# ---------------------------------------------------------------------------
# Dispatch matching
# ---------------------------------------------------------------------------

class TestEventRegistryDispatch:
    @pytest.mark.asyncio
    async def test_isinstance_match(self, registry: EventRegistry, trace_root: TraceContext) -> None:
        """Subscriber for BeforeInvokeEvent only receives BeforeInvokeEvent."""
        received = []

        async def cb(e: LifecycleEvent) -> None:
            received.append(e)

        registry.subscribe(BeforeInvokeEvent, cb)
        await registry.emit(BeforeInvokeEvent(trace_context=trace_root))
        await registry.emit(AfterInvokeEvent(trace_context=trace_root))
        assert len(received) == 1
        assert isinstance(received[0], BeforeInvokeEvent)

    @pytest.mark.asyncio
    async def test_subclass_subscription(self, registry: EventRegistry, trace_root: TraceContext) -> None:
        """Subscribing to LifecycleEvent (parent) receives every concrete event."""
        received = []

        async def cb(e: LifecycleEvent) -> None:
            received.append(e)

        registry.subscribe(LifecycleEvent, cb)
        await registry.emit(BeforeInvokeEvent(trace_context=trace_root))
        await registry.emit(AfterInvokeEvent(trace_context=trace_root))
        assert len(received) == 2

    @pytest.mark.asyncio
    async def test_no_match_other_subtype(self, registry: EventRegistry, trace_root: TraceContext) -> None:
        """BeforeToolCallEvent subscriber does not receive AfterToolCallEvent."""
        received = []

        async def cb(e: LifecycleEvent) -> None:
            received.append(e)

        registry.subscribe(BeforeToolCallEvent, cb)
        await registry.emit(AfterToolCallEvent(trace_context=trace_root))
        assert len(received) == 0


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------

class TestDispatchOrdering:
    @pytest.mark.asyncio
    async def test_normal_order_before_event(self, registry: EventRegistry, trace_root: TraceContext) -> None:
        """Before* events dispatch subscribers in forward (insertion) order."""
        order: list[str] = []

        async def a(e: LifecycleEvent) -> None:
            order.append("a")

        async def b(e: LifecycleEvent) -> None:
            order.append("b")

        registry.subscribe(BeforeInvokeEvent, a)
        registry.subscribe(BeforeInvokeEvent, b)
        await registry.emit(BeforeInvokeEvent(trace_context=trace_root))
        assert order == ["a", "b"]

    @pytest.mark.asyncio
    async def test_reverse_order_after_event(self, registry: EventRegistry, trace_root: TraceContext) -> None:
        """After* events dispatch subscribers in REVERSE (cleanup symmetry) order."""
        order: list[str] = []

        async def a(e: LifecycleEvent) -> None:
            order.append("a")

        async def b(e: LifecycleEvent) -> None:
            order.append("b")

        registry.subscribe(AfterInvokeEvent, a)
        registry.subscribe(AfterInvokeEvent, b)
        await registry.emit(AfterInvokeEvent(trace_context=trace_root))
        assert order == ["b", "a"]

    @pytest.mark.asyncio
    async def test_reverse_order_failed_event(self, registry: EventRegistry, trace_root: TraceContext) -> None:
        """*Failed events dispatch subscribers in REVERSE order."""
        order: list[str] = []

        async def a(e: LifecycleEvent) -> None:
            order.append("a")

        async def b(e: LifecycleEvent) -> None:
            order.append("b")

        registry.subscribe(InvokeFailedEvent, a)
        registry.subscribe(InvokeFailedEvent, b)
        await registry.emit(InvokeFailedEvent(trace_context=trace_root))
        assert order == ["b", "a"]


# ---------------------------------------------------------------------------
# Where filter
# ---------------------------------------------------------------------------

class TestWhereFilter:
    @pytest.mark.asyncio
    async def test_where_filter_accepted(self, registry: EventRegistry, trace_root: TraceContext) -> None:
        """where= predicate receives only matching events."""
        received = []

        async def cb(e: BeforeToolCallEvent) -> None:
            received.append(e)

        registry.subscribe(
            BeforeToolCallEvent, cb,
            where=lambda e: e.tool_name == "keep",
        )
        await registry.emit(BeforeToolCallEvent(trace_context=trace_root, tool_name="drop"))
        await registry.emit(BeforeToolCallEvent(trace_context=trace_root, tool_name="keep"))
        assert [e.tool_name for e in received] == ["keep"]

    @pytest.mark.asyncio
    async def test_where_filter_none_passes_all(self, registry: EventRegistry, trace_root: TraceContext) -> None:
        """When where=None (default) all matching events are dispatched."""
        received = []

        async def cb(e: LifecycleEvent) -> None:
            received.append(e)

        registry.subscribe(BeforeInvokeEvent, cb, where=None)
        await registry.emit(BeforeInvokeEvent(trace_context=trace_root))
        await registry.emit(BeforeInvokeEvent(trace_context=trace_root))
        assert len(received) == 2


# ---------------------------------------------------------------------------
# Error isolation
# ---------------------------------------------------------------------------

class TestErrorIsolation:
    @pytest.mark.asyncio
    async def test_subscriber_exception_does_not_propagate(
        self, registry: EventRegistry, trace_root: TraceContext
    ) -> None:
        """emit() never raises when a subscriber raises."""
        async def boom(e: LifecycleEvent) -> None:
            raise RuntimeError("boom")

        registry.subscribe(BeforeInvokeEvent, boom)
        # Must NOT raise
        await registry.emit(BeforeInvokeEvent(trace_context=trace_root))

    @pytest.mark.asyncio
    async def test_subsequent_subscriber_runs_after_failure(
        self, registry: EventRegistry, trace_root: TraceContext
    ) -> None:
        """After a subscriber raises, remaining subscribers still run."""
        survived: list[LifecycleEvent] = []

        async def boom(e: LifecycleEvent) -> None:
            raise RuntimeError("boom")

        async def survivor(e: LifecycleEvent) -> None:
            survived.append(e)

        registry.subscribe(BeforeInvokeEvent, boom)
        registry.subscribe(BeforeInvokeEvent, survivor)
        await registry.emit(BeforeInvokeEvent(trace_context=trace_root))
        assert len(survived) == 1

    @pytest.mark.asyncio
    async def test_subscriber_error_event_scheduled(
        self, registry: EventRegistry, trace_root: TraceContext
    ) -> None:
        """A SubscriberErrorEvent is scheduled to the global registry when a subscriber fails."""
        import sys
        import types

        async def boom(e: LifecycleEvent) -> None:
            raise ValueError("test error")

        registry.subscribe(BeforeInvokeEvent, boom)

        mock_global = MagicMock()
        mock_global._emit_meta = AsyncMock()

        # get_global_registry is lazily imported inside _emit_subscriber_error.
        # Inject a fake module into sys.modules so the lazy import resolves.
        fake_module = types.ModuleType("navigator_eventbus.lifecycle.global_registry")
        fake_module.get_global_registry = MagicMock(return_value=mock_global)

        sys.modules.setdefault(
            "navigator_eventbus.lifecycle.global_registry", fake_module
        )
        original = sys.modules.get("navigator_eventbus.lifecycle.global_registry")
        sys.modules["navigator_eventbus.lifecycle.global_registry"] = fake_module
        try:
            await registry.emit(BeforeInvokeEvent(trace_context=trace_root))
            # Allow the scheduled task to run
            await asyncio.sleep(0)
        finally:
            if original is None:
                del sys.modules["navigator_eventbus.lifecycle.global_registry"]
            else:
                sys.modules["navigator_eventbus.lifecycle.global_registry"] = original

        # _emit_meta was called once on the global registry
        mock_global._emit_meta.assert_called_once()
        err_evt = mock_global._emit_meta.call_args[0][0]
        assert isinstance(err_evt, SubscriberErrorEvent)
        assert err_evt.error_type == "ValueError"
        assert "test error" in err_evt.error_message
        assert err_evt.original_event_class == "BeforeInvokeEvent"


# ---------------------------------------------------------------------------
# Recursion guard
# ---------------------------------------------------------------------------

class TestRecursionGuard:
    @pytest.mark.asyncio
    async def test_recursion_guard_prevents_infinite_loop(
        self, registry: EventRegistry, trace_root: TraceContext
    ) -> None:
        """_emit_meta drops nested calls when _emitting_meta is True."""
        call_count = 0

        async def raises_on_meta(e: LifecycleEvent) -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("nested failure")

        registry.subscribe(SubscriberErrorEvent, raises_on_meta)

        err_evt = SubscriberErrorEvent(
            trace_context=trace_root,
            failed_subscriber="dummy",
            original_event_class="BeforeInvokeEvent",
            error_type="RuntimeError",
            error_message="original",
            traceback="",
        )
        # _emit_meta with a SubscriberErrorEvent subscriber that also raises
        # should NOT recurse indefinitely.
        await registry._emit_meta(err_evt)
        # Should only be called once (the initial _emit_meta sets the guard,
        # so when the error-emitting path tries to schedule another _emit_meta
        # it is blocked)
        assert call_count <= 1


# ---------------------------------------------------------------------------
# Subscription management
# ---------------------------------------------------------------------------

class TestSubscriptionManagement:
    @pytest.mark.asyncio
    async def test_subscribe_returns_unique_id(
        self, registry: EventRegistry
    ) -> None:
        """subscribe() returns a non-empty unique string per call."""
        async def cb(e: LifecycleEvent) -> None:
            pass

        id1 = registry.subscribe(BeforeInvokeEvent, cb)
        id2 = registry.subscribe(BeforeInvokeEvent, cb)
        assert id1 and id2
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_subscriber(
        self, registry: EventRegistry, trace_root: TraceContext
    ) -> None:
        """unsubscribe() prevents the subscriber from receiving future events."""
        received: list[LifecycleEvent] = []

        async def cb(e: LifecycleEvent) -> None:
            received.append(e)

        sub_id = registry.subscribe(BeforeInvokeEvent, cb)
        await registry.emit(BeforeInvokeEvent(trace_context=trace_root))
        assert len(received) == 1

        removed = registry.unsubscribe(sub_id)
        assert removed is True
        await registry.emit(BeforeInvokeEvent(trace_context=trace_root))
        assert len(received) == 1  # No new events

    def test_unsubscribe_unknown_id_returns_false(self, registry: EventRegistry) -> None:
        """unsubscribe() returns False for an unknown subscription_id."""
        assert registry.unsubscribe("nonexistent-id") is False


# ---------------------------------------------------------------------------
# Dual-emit opt-in
# ---------------------------------------------------------------------------

class TestDualEmit:
    @pytest.mark.asyncio
    async def test_forward_to_bus_false_no_bus_calls(
        self, trace_root: TraceContext
    ) -> None:
        """forward_to_bus=False → zero EventBus.emit calls."""
        from navigator_eventbus.evb import EventBus
        bus = EventBus(use_redis=False)
        bus.emit = AsyncMock()  # type: ignore[method-assign]
        reg = EventRegistry(event_bus=bus, forward_to_global=False)

        async def cb(e: LifecycleEvent) -> None:
            pass

        reg.subscribe(BeforeInvokeEvent, cb, forward_to_bus=False)
        await reg.emit(BeforeInvokeEvent(trace_context=trace_root))
        assert bus.emit.call_count == 0

    @pytest.mark.asyncio
    async def test_forward_to_bus_true_one_bus_call(
        self, trace_root: TraceContext
    ) -> None:
        """forward_to_bus=True → exactly one EventBus.emit call per event."""
        from navigator_eventbus.evb import EventBus
        bus = EventBus(use_redis=False)
        bus.emit = AsyncMock()  # type: ignore[method-assign]
        reg = EventRegistry(event_bus=bus, forward_to_global=False)

        async def cb(e: LifecycleEvent) -> None:
            pass

        reg.subscribe(BeforeInvokeEvent, cb, forward_to_bus=True)
        await reg.emit(BeforeInvokeEvent(trace_context=trace_root))
        assert bus.emit.call_count == 1

    @pytest.mark.asyncio
    async def test_dual_emit_opt_in_roundtrip(
        self, trace_root: TraceContext
    ) -> None:
        """Combining forward_to_bus=False and =True on the same registry works."""
        from navigator_eventbus.evb import EventBus
        bus = EventBus(use_redis=False)
        bus.emit = AsyncMock()  # type: ignore[method-assign]
        reg = EventRegistry(event_bus=bus, forward_to_global=False)

        async def cb(e: LifecycleEvent) -> None:
            pass

        # First subscription: no bus
        reg.subscribe(BeforeInvokeEvent, cb, forward_to_bus=False)
        await reg.emit(BeforeInvokeEvent(trace_context=trace_root))
        assert bus.emit.call_count == 0

        # Second subscription: with bus
        reg.subscribe(BeforeInvokeEvent, cb, forward_to_bus=True)
        await reg.emit(BeforeInvokeEvent(trace_context=trace_root))
        # Only the second subscriber forwards → exactly 1 more call
        assert bus.emit.call_count == 1

    @pytest.mark.asyncio
    async def test_stream_chunk_no_auto_forward(
        self, trace_root: TraceContext
    ) -> None:
        """1000 ClientStreamChunkEvents with forward_to_bus=False → zero bus calls."""
        from navigator_eventbus.evb import EventBus
        bus = EventBus(use_redis=False)
        bus.emit = AsyncMock()  # type: ignore[method-assign]
        reg = EventRegistry(event_bus=bus, forward_to_global=False)

        async def cb(e: LifecycleEvent) -> None:
            pass

        reg.subscribe(ClientStreamChunkEvent, cb, forward_to_bus=False)
        for i in range(1000):
            await reg.emit(ClientStreamChunkEvent(trace_context=trace_root, chunk_index=i))
        assert bus.emit.call_count == 0
