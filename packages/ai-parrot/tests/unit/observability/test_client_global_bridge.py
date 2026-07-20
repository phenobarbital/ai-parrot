"""Unit tests for the client->global event bridge (EventRegistry.forward_to_global).

The fix that lets isolated client registries (forward_to_global=False) deliver
their LLM-call lifecycle events to global observers (cost/token recorders, OTel
subscribers) without forwarding every event (e.g. stream chunks stay isolated).
"""

from __future__ import annotations

import asyncio

import pytest

from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    ClientStreamChunkEvent,
)
from navigator_eventbus.lifecycle.global_registry import get_global_registry, scope
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.lifecycle.trace import TraceContext


def _after() -> AfterClientCallEvent:
    return AfterClientCallEvent(
        trace_context=TraceContext.new_root(), client_name="openai", model="gpt-4o",
        duration_ms=1.0, input_tokens=5, output_tokens=2,
        source_type="client", source_name="openai",
    )


@pytest.mark.asyncio
async def test_plain_emit_does_not_reach_global() -> None:
    """An isolated registry's plain emit stays local (does not reach global)."""
    received: list = []
    with scope():
        get_global_registry().subscribe(AfterClientCallEvent, _collect(received))
        client_reg = EventRegistry(forward_to_global=False)
        await client_reg.emit(_after())
        await asyncio.sleep(0)
        assert received == []


@pytest.mark.asyncio
async def test_forward_to_global_delivers_event() -> None:
    """forward_to_global delivers the event to a global subscriber."""
    received: list = []
    with scope():
        get_global_registry().subscribe(AfterClientCallEvent, _collect(received))
        client_reg = EventRegistry(forward_to_global=False)
        ev = _after()
        client_reg.forward_to_global(ev)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(received) == 1
        assert received[0] is ev


@pytest.mark.asyncio
async def test_forward_skipped_when_no_global_subscriber() -> None:
    """forward_to_global is a safe no-op when nobody listens for that type."""
    with scope():
        # Only AfterClientCallEvent has a listener; stream chunks have none.
        get_global_registry().subscribe(AfterClientCallEvent, _collect([]))
        client_reg = EventRegistry(forward_to_global=False)
        chunk = ClientStreamChunkEvent(
            trace_context=TraceContext.new_root(), client_name="openai",
            model="gpt-4o", chunk_index=0, chunk_size_bytes=3,
        )
        # Must not raise and must not schedule anything observable.
        client_reg.forward_to_global(chunk)
        await asyncio.sleep(0)


def _collect(sink: list):
    async def _cb(event) -> None:
        sink.append(event)
    return _cb
