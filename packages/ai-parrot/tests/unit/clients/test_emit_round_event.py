"""Unit tests for AbstractClient._emit_round_event() (FEAT-397).

Uses the same minimal fake-concrete-client pattern as
test_client_lifecycle.py — a stub AbstractClient subclass with no-op
ask/ask_stream bodies, so no real LLM credentials are required.
"""
from __future__ import annotations

import asyncio

import pytest

from parrot.core.events.lifecycle.events import ClientRoundEvent
from parrot.models.basic import CompletionUsage
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.observability.context import current_agent_name


def _make_stub_client():
    """Return a minimal AbstractClient subclass instance that skips all I/O."""
    from parrot.clients.base import AbstractClient

    class _StubClient(AbstractClient):
        """Stub that implements the abstract ask/ask_stream with no-op bodies."""

        client_name = "stub"

        def __init__(self):
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


def _capture():
    """Return (captured_list, async_callback)."""
    captured: list = []

    async def cb(event):
        captured.append(event)

    return captured, cb


class TestEmitRoundEvent:
    """Verify AbstractClient._emit_round_event() short-circuit + payload mapping."""

    def test_short_circuit_no_subscribers(self) -> None:
        """Zero subscribers → the event is never constructed (emit_nowait never called)."""
        client = _make_stub_client()
        assert client.events.has_subscribers(ClientRoundEvent) is False

        tc = TraceContext.new_root()
        # Should be a pure no-op: no exception, no event delivered anywhere.
        client._emit_round_event(
            tc,
            client_name="stub",
            model="stub-model",
            round_number=1,
            usage=CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            raw_usage={"prompt_tokens": 10},
            tool_calls=["get_weather"],
            duration_ms=12.0,
        )
        # No subscribers means nothing was captured anywhere — nothing to assert
        # on directly except that has_subscribers is still False and no error raised.
        assert client.events.has_subscribers(ClientRoundEvent) is False

    @pytest.mark.asyncio
    async def test_event_payload_mapping(self) -> None:
        """usage tokens map onto flat input/output/total; tool_calls coerced to tuple."""
        client = _make_stub_client()
        captured, cb = _capture()
        client.events.subscribe(ClientRoundEvent, cb)

        tc = TraceContext.new_root()
        usage = CompletionUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        client._emit_round_event(
            tc,
            client_name="stub",
            model="stub-model",
            round_number=2,
            usage=usage,
            raw_usage={"prompt_tokens": 10, "completion_tokens": 5},
            tool_calls=["get_weather", "search"],
            duration_ms=42.0,
        )
        await asyncio.sleep(0)  # drain emit_nowait

        assert len(captured) == 1
        event = captured[0]
        assert isinstance(event, ClientRoundEvent)
        assert event.round_number == 2
        assert event.input_tokens == 10
        assert event.output_tokens == 5
        assert event.total_tokens == 15
        assert event.tool_calls == ("get_weather", "search")
        assert event.raw_usage == {"prompt_tokens": 10, "completion_tokens": 5}
        assert event.duration_ms == 42.0
        assert event.trace_context is tc

    @pytest.mark.asyncio
    async def test_usage_none_maps_to_none_tokens(self) -> None:
        """usage=None → input/output/total tokens are all None (accumulator skips round)."""
        client = _make_stub_client()
        captured, cb = _capture()
        client.events.subscribe(ClientRoundEvent, cb)

        tc = TraceContext.new_root()
        client._emit_round_event(
            tc,
            client_name="stub",
            model="stub-model",
            round_number=1,
            usage=None,
            raw_usage=None,
            tool_calls=(),
            duration_ms=5.0,
        )
        await asyncio.sleep(0)

        assert len(captured) == 1
        event = captured[0]
        assert event.input_tokens is None
        assert event.output_tokens is None
        assert event.total_tokens is None
        assert event.tool_calls == ()
        assert event.raw_usage is None

    @pytest.mark.asyncio
    async def test_agent_name_from_contextvar(self) -> None:
        """agent_name is populated from the FEAT-228 ContextVar at construction time."""
        client = _make_stub_client()
        captured, cb = _capture()
        client.events.subscribe(ClientRoundEvent, cb)

        token = current_agent_name.set("bot-a")
        try:
            tc = TraceContext.new_root()
            client._emit_round_event(
                tc,
                client_name="stub",
                model="stub-model",
                round_number=1,
                usage=None,
                raw_usage=None,
                tool_calls=(),
                duration_ms=1.0,
            )
            await asyncio.sleep(0)
        finally:
            current_agent_name.reset(token)

        assert len(captured) == 1
        assert captured[0].agent_name == "bot-a"
