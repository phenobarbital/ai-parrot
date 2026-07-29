"""Unit tests for EventProvider Protocol and EventRegistry.add_provider().

FEAT-176 — Lifecycle Events System (TASK-1188).
"""
from __future__ import annotations

import pytest

from navigator_eventbus.lifecycle.provider import EventProvider
from navigator_eventbus.lifecycle.registry import EventRegistry
from parrot.core.events.lifecycle.events import (
    AfterInvokeEvent,
    BeforeInvokeEvent,
    InvokeFailedEvent,
)
from navigator_eventbus.lifecycle.trace import TraceContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _GoodProvider:
    """Provider that registers two subscribers."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def register(self, registry: EventRegistry) -> None:
        async def on_start(e: BeforeInvokeEvent) -> None:
            self.calls.append("start")

        async def on_end(e: AfterInvokeEvent) -> None:
            self.calls.append("end")

        registry.subscribe(BeforeInvokeEvent, on_start)
        registry.subscribe(AfterInvokeEvent, on_end)


class _ThreeSubscriberProvider:
    """Provider that registers three subscribers."""

    def register(self, registry: EventRegistry) -> None:
        async def noop(e: object) -> None:
            pass

        registry.subscribe(BeforeInvokeEvent, noop)
        registry.subscribe(AfterInvokeEvent, noop)
        registry.subscribe(InvokeFailedEvent, noop)


class _BadProvider:
    """Does not implement register() — non-conforming."""
    pass


class _WrongSignatureProvider:
    """Has a register attribute but it's not callable."""
    register = "not a method"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEventProvider:
    def test_conformance_good_provider(self) -> None:
        """An object with register(registry) conforms to EventProvider."""
        assert isinstance(_GoodProvider(), EventProvider)

    def test_conformance_bad_provider(self) -> None:
        """An object without register() does not conform."""
        assert not isinstance(_BadProvider(), EventProvider)

    def test_add_provider_returns_ids(self) -> None:
        """add_provider() returns the IDs of newly created subscriptions."""
        reg = EventRegistry(forward_to_global=False)
        ids = reg.add_provider(_GoodProvider())
        assert len(ids) == 2
        assert all(isinstance(sid, str) for sid in ids)

    def test_add_provider_returns_three_ids(self) -> None:
        """add_provider() handles providers that register three callbacks."""
        reg = EventRegistry(forward_to_global=False)
        ids = reg.add_provider(_ThreeSubscriberProvider())
        assert len(ids) == 3

    def test_add_provider_ids_are_unique(self) -> None:
        """Each subscription ID returned by add_provider is unique."""
        reg = EventRegistry(forward_to_global=False)
        ids = reg.add_provider(_ThreeSubscriberProvider())
        assert len(set(ids)) == len(ids)

    def test_add_provider_rejects_non_conforming(self) -> None:
        """add_provider() raises TypeError for non-EventProvider objects."""
        reg = EventRegistry(forward_to_global=False)
        with pytest.raises(TypeError, match="not an EventProvider"):
            reg.add_provider(_BadProvider())

    def test_add_provider_ids_valid_for_unsubscribe(self) -> None:
        """IDs returned by add_provider can be used to unsubscribe."""
        reg = EventRegistry(forward_to_global=False)
        ids = reg.add_provider(_GoodProvider())
        assert len(reg._subscriptions) == 2

        for sid in ids:
            reg.unsubscribe(sid)

        assert len(reg._subscriptions) == 0

    @pytest.mark.asyncio
    async def test_provider_callbacks_invoked(self) -> None:
        """Callbacks registered via add_provider are actually invoked on emit."""
        reg = EventRegistry(forward_to_global=False)
        provider = _GoodProvider()
        reg.add_provider(provider)

        trace = TraceContext.new_root()
        await reg.emit(BeforeInvokeEvent(trace_context=trace))
        await reg.emit(AfterInvokeEvent(trace_context=trace))

        assert provider.calls == ["start", "end"]

    def test_add_provider_does_not_return_pre_existing_ids(self) -> None:
        """IDs added before the provider call are NOT returned."""
        reg = EventRegistry(forward_to_global=False)

        async def pre_existing(e: object) -> None:
            pass

        pre_id = reg.subscribe(BeforeInvokeEvent, pre_existing)
        ids = reg.add_provider(_GoodProvider())

        assert pre_id not in ids
        assert len(ids) == 2
