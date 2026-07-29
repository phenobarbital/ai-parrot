"""Unit tests for AbstractClient lifecycle event integration.

FEAT-176 — Lifecycle Events System (TASK-1194).

Uses a minimal fake concrete client to test Before/After/Failed events
and the stream-chunk hot-path short-circuit — without requiring real
LLM credentials.
"""
from __future__ import annotations

import asyncio
import hashlib

import pytest

from parrot.core.events.lifecycle.events import (
    BeforeClientCallEvent,
    AfterClientCallEvent,
    ClientCallFailedEvent,
    ClientStreamChunkEvent,
)
from navigator_eventbus.lifecycle.trace import TraceContext
from navigator_eventbus.lifecycle.registry import EventRegistry


# ---------------------------------------------------------------------------
# Minimal fake AbstractClient subclass (no LLM, no extra deps)
# ---------------------------------------------------------------------------

def _make_stub_client():
    """Return a minimal AbstractClient subclass instance that skips all I/O."""
    from parrot.clients.base import AbstractClient

    class _StubClient(AbstractClient):
        """Stub that implements the abstract ask/ask_stream with no-op bodies."""

        client_name = "stub"

        def __init__(self):
            # Call AbstractClient.__init__ with minimal kwargs
            super().__init__(debug=False)

        async def ask(self, prompt: str, model: str = "stub-model", **kw):  # type: ignore[override]
            raise NotImplementedError("stub")

        async def ask_stream(self, prompt: str, **kw):  # type: ignore[override]
            raise NotImplementedError("stub")
            yield  # makes it an async generator

        async def get_client(self):
            return None

        async def _ensure_client(self):
            pass

        async def invoke(self, *args, **kwargs):  # type: ignore[override]
            raise NotImplementedError("stub")

        async def resume(self, *args, **kwargs):  # type: ignore[override]
            raise NotImplementedError("stub")

    return _StubClient()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _capture():
    """Return (captured_list, async_callback)."""
    captured: list = []

    async def cb(event):
        captured.append(event)

    return captured, cb


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestClientLifecycle:
    """Verify lifecycle events from AbstractClient emission helpers."""

    def test_abstract_client_exposes_events(self) -> None:
        """AbstractClient exposes self.events (EventRegistry) after __init__."""
        client = _make_stub_client()
        assert isinstance(client.events, EventRegistry)

    def test_has_subscribers_false_when_empty(self) -> None:
        """has_subscribers returns False when no subscriptions exist."""
        client = _make_stub_client()
        assert client.events.has_subscribers(BeforeClientCallEvent) is False

    def test_has_subscribers_true_after_subscribe(self) -> None:
        """has_subscribers returns True after subscribing."""
        client = _make_stub_client()

        async def dummy(e):
            pass

        client.events.subscribe(BeforeClientCallEvent, dummy)
        assert client.events.has_subscribers(BeforeClientCallEvent) is True

    def test_has_subscribers_broad_lifecycle_matches_chunk(self) -> None:
        """Subscribing to LifecycleEvent also matches ClientStreamChunkEvent."""
        from navigator_eventbus.lifecycle.base import LifecycleEvent
        client = _make_stub_client()

        async def dummy(e):
            pass

        client.events.subscribe(LifecycleEvent, dummy)
        assert client.events.has_subscribers(ClientStreamChunkEvent) is True

    def test_system_prompt_hash_empty_for_none(self) -> None:
        """_system_prompt_hash returns '' when system_prompt is None."""
        client = _make_stub_client()
        assert client._system_prompt_hash(None) == ""

    def test_system_prompt_hash_is_sha256(self) -> None:
        """_system_prompt_hash returns SHA-256 hex for a non-empty string."""
        client = _make_stub_client()
        sp = "You are a helpful assistant."
        expected = hashlib.sha256(sp.encode()).hexdigest()
        assert client._system_prompt_hash(sp) == expected

    @pytest.mark.asyncio
    async def test_success_emits_before_and_after(self) -> None:
        """Before is emitted first, After is emitted on success — never both on failure."""
        client = _make_stub_client()
        captured, cb = _capture()
        client.events.subscribe(BeforeClientCallEvent, cb)
        client.events.subscribe(AfterClientCallEvent, cb)

        tc = client._emit_before_call(
            client_name="stub",
            model="stub-model",
            temperature=0.7,
            system_prompt="test",
            has_tools=False,
        )
        await asyncio.sleep(0)  # drain emit_nowait
        await client._emit_after_call(
            tc,
            client_name="stub",
            model="stub-model",
            duration_ms=100.0,
            input_tokens=10,
            output_tokens=20,
            finish_reason="stop",
        )

        types = [type(e).__name__ for e in captured]
        assert "BeforeClientCallEvent" in types
        assert "AfterClientCallEvent" in types

        before = next(e for e in captured if isinstance(e, BeforeClientCallEvent))
        after = next(e for e in captured if isinstance(e, AfterClientCallEvent))
        assert before.client_name == "stub"
        assert after.duration_ms == 100.0
        assert after.input_tokens == 10
        assert after.output_tokens == 20
        assert after.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_failure_emits_failed_not_after(self) -> None:
        """On failure: Before + Failed are emitted; AfterClientCallEvent is NOT."""
        client = _make_stub_client()
        before_evts, before_cb = _capture()
        after_evts, after_cb = _capture()
        failed_evts, failed_cb = _capture()
        client.events.subscribe(BeforeClientCallEvent, before_cb)
        client.events.subscribe(AfterClientCallEvent, after_cb)
        client.events.subscribe(ClientCallFailedEvent, failed_cb)

        tc = client._emit_before_call(
            client_name="stub",
            model="stub-model",
            temperature=None,
            system_prompt=None,
            has_tools=False,
        )
        await asyncio.sleep(0)
        await client._emit_failed_call(
            tc,
            client_name="stub",
            model="stub-model",
            duration_ms=50.0,
            exc=RuntimeError("LLM down"),
        )

        assert len(before_evts) == 1
        assert len(failed_evts) == 1
        assert len(after_evts) == 0  # AfterClientCallEvent MUST NOT be emitted on failure

        assert failed_evts[0].error_type == "RuntimeError"
        assert failed_evts[0].error_message == "LLM down"

    @pytest.mark.asyncio
    async def test_trace_context_threaded(self) -> None:
        """Parent TraceContext is threaded to the Before event via child span."""
        client = _make_stub_client()
        captured, cb = _capture()
        client.events.subscribe(BeforeClientCallEvent, cb)

        parent = TraceContext.new_root()
        tc = client._emit_before_call(
            client_name="stub",
            model="stub-model",
            temperature=0.5,
            system_prompt=None,
            has_tools=False,
            parent_trace=parent,
        )
        await asyncio.sleep(0)

        # Child span must share trace_id and reference parent span_id
        assert tc.trace_id == parent.trace_id
        assert tc.parent_span_id == parent.span_id

        assert len(captured) >= 1
        assert captured[0].trace_context.parent_span_id == parent.span_id

    @pytest.mark.asyncio
    async def test_no_parent_creates_root(self) -> None:
        """When parent_trace=None a new root TraceContext is created."""
        client = _make_stub_client()
        captured, cb = _capture()
        client.events.subscribe(BeforeClientCallEvent, cb)

        tc = client._emit_before_call(
            client_name="stub",
            model="stub-model",
            temperature=None,
            system_prompt=None,
            has_tools=False,
            parent_trace=None,
        )
        await asyncio.sleep(0)

        assert tc.parent_span_id is None
        assert len(captured) >= 1

    @pytest.mark.asyncio
    async def test_stream_chunk_short_circuit_no_subscribers(self) -> None:
        """1000-chunk loop with no ClientStreamChunkEvent subscriber → zero emit calls."""
        client = _make_stub_client()

        # No subscriber → has_subscribers must be False
        has_subs = client.events.has_subscribers(ClientStreamChunkEvent)
        assert has_subs is False

        # Simulate the short-circuit: the hot loop checks has_subs ONCE before iteration
        emit_calls: list = []
        for i in range(1000):
            if has_subs:  # short-circuit: this branch never executes
                emit_calls.append(i)

        assert len(emit_calls) == 0

    @pytest.mark.asyncio
    async def test_stream_chunk_emits_when_subscribed(self) -> None:
        """ClientStreamChunkEvent is emitted per chunk when a subscriber is present."""
        client = _make_stub_client()
        captured, cb = _capture()
        client.events.subscribe(ClientStreamChunkEvent, cb)

        has_subs = client.events.has_subscribers(ClientStreamChunkEvent)
        assert has_subs is True

        tc = TraceContext.new_root()
        for i in range(5):
            if has_subs:
                await client.events.emit(ClientStreamChunkEvent(
                    trace_context=tc,
                    client_name="stub",
                    model="stub-model",
                    chunk_index=i,
                    chunk_size_bytes=8,
                    source_type="client",
                    source_name="stub",
                ))

        assert len(captured) == 5
        assert captured[0].chunk_index == 0
        assert captured[4].chunk_index == 4
