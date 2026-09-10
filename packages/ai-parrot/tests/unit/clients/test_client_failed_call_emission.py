"""Unit tests for ClientCallFailedEvent emission on LLM API errors.

Verifies that when a client's ask()/ask_stream() raises, the
``_emit_failed_call`` lifecycle hook fires — closing the span opened by
``_emit_before_call`` and incrementing ``gen_ai.client.error.count``.

Root-cause fix for FEAT-548 Finding #1: ``gen_ai.client.error.count``
never observed to emit because ``_emit_failed_call`` was dead code in
most client implementations.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.core.events.lifecycle.events import (
    BeforeClientCallEvent,
    ClientCallFailedEvent,
)
from navigator_eventbus.lifecycle.registry import EventRegistry


# ---------------------------------------------------------------------------
# Minimal OpenAIBaseClient stub (no real SDK)
# ---------------------------------------------------------------------------

def _make_openai_stub(*, raise_on_completion: Exception | None = None):
    """Return an OpenAIBaseClient subclass that fakes _chat_completion."""
    from parrot.clients.openai_base import OpenAIBaseClient

    class _Stub(OpenAIBaseClient):
        client_name = "stub-openai"
        client_type = "stub"
        model = "stub-model"

        def __init__(self):
            super().__init__(debug=False)
            self._raise_on_completion = raise_on_completion

        async def get_client(self):
            return MagicMock()

        async def _ensure_client(self):
            pass

        async def invoke(self, *args, **kwargs):
            raise NotImplementedError("stub")

        async def resume(self, *args, **kwargs):
            raise NotImplementedError("stub")

        async def _chat_completion(self, **kwargs):
            if self._raise_on_completion:
                raise self._raise_on_completion
            # Minimal response shape for the happy path (not used in error tests)
            msg = MagicMock()
            msg.content = "hello"
            msg.tool_calls = None
            choice = MagicMock()
            choice.message = msg
            choice.finish_reason = "stop"
            resp = MagicMock()
            resp.choices = [choice]
            resp.usage = MagicMock(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            )
            return resp

    return _Stub()


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
# Tests — OpenAIBaseClient
# ---------------------------------------------------------------------------

class TestOpenAIBaseClientFailedCallEmission:
    """Verify _emit_failed_call fires when ask()/ask_stream() raise."""

    @pytest.mark.asyncio
    async def test_ask_error_emits_failed_event(self) -> None:
        """ask() raises → ClientCallFailedEvent emitted with correct error_type."""
        client = _make_openai_stub(raise_on_completion=RuntimeError("model on fire"))
        before_evts, before_cb = _capture()
        failed_evts, failed_cb = _capture()
        client.events.subscribe(BeforeClientCallEvent, before_cb)
        client.events.subscribe(ClientCallFailedEvent, failed_cb)

        with pytest.raises(RuntimeError, match="model on fire"):
            await client.ask(prompt="hello", model="stub-model")

        # Drain emit_nowait tasks
        await asyncio.sleep(0.05)

        assert len(before_evts) >= 1, "BeforeClientCallEvent should fire"
        assert len(failed_evts) == 1, "ClientCallFailedEvent should fire exactly once"
        assert failed_evts[0].error_type == "RuntimeError"
        assert "model on fire" in failed_evts[0].error_message

    @pytest.mark.asyncio
    async def test_ask_error_does_not_emit_after(self) -> None:
        """ask() raises → AfterClientCallEvent must NOT be emitted."""
        from parrot.core.events.lifecycle.events import AfterClientCallEvent

        client = _make_openai_stub(raise_on_completion=ValueError("bad request"))
        after_evts, after_cb = _capture()
        client.events.subscribe(AfterClientCallEvent, after_cb)

        with pytest.raises(ValueError, match="bad request"):
            await client.ask(prompt="hello", model="stub-model")

        await asyncio.sleep(0.05)
        assert len(after_evts) == 0, "AfterClientCallEvent must NOT fire on error"

    @pytest.mark.asyncio
    async def test_ask_stream_error_emits_failed_event(self) -> None:
        """ask_stream() raises on _chat_completion → ClientCallFailedEvent emitted."""
        client = _make_openai_stub(raise_on_completion=ConnectionError("network down"))
        failed_evts, failed_cb = _capture()
        client.events.subscribe(ClientCallFailedEvent, failed_cb)

        with pytest.raises(ConnectionError, match="network down"):
            async for _ in client.ask_stream(prompt="hello", model="stub-model"):
                pass

        await asyncio.sleep(0.05)
        assert len(failed_evts) == 1
        assert failed_evts[0].error_type == "ConnectionError"

    @pytest.mark.asyncio
    async def test_failed_event_forwarded_to_global(self) -> None:
        """ClientCallFailedEvent is forwarded to the global EventRegistry."""
        from navigator_eventbus.lifecycle.global_registry import get_global_registry

        global_reg = get_global_registry()
        global_captured, global_cb = _capture()
        global_reg.subscribe(ClientCallFailedEvent, global_cb)

        try:
            client = _make_openai_stub(
                raise_on_completion=RuntimeError("forwarded error"),
            )
            with pytest.raises(RuntimeError):
                await client.ask(prompt="hello", model="stub-model")
            await asyncio.sleep(0.05)

            assert len(global_captured) >= 1, (
                "ClientCallFailedEvent should reach the global registry"
            )
            assert global_captured[0].error_type == "RuntimeError"
        finally:
            # Clean up global subscription — unsubscribe takes (callback) only;
            # or clear listeners for this event type if available.
            try:
                global_reg.unsubscribe(global_cb)
            except Exception:
                pass  # best-effort cleanup
