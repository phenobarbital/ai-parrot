"""Unit tests for lifecycle-event emission from OpenAIBaseClient.invoke() (FEAT-579).

``ask()`` has emitted BeforeClientCallEvent / AfterClientCallEvent /
ClientCallFailedEvent for some time; ``invoke()`` emitted nothing, so every
invoke call was missing from token, cost and latency telemetry.
"""

from __future__ import annotations

import asyncio
import weakref
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from parrot.clients.base import _LoopClientEntry
from parrot.clients.openai_base import OpenAIBaseClient
from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    BeforeClientCallEvent,
    ClientCallFailedEvent,
)
from parrot.core.exceptions import BudgetExhausted
from parrot.exceptions import InvokeError
from parrot.models.responses import InvokeResult


def _capture():
    """Return ``(captured, async_callback)`` for one event class."""
    captured: list = []

    async def cb(event):
        captured.append(event)

    return captured, cb


def _make_stub(*, raise_on_completion: Exception | None = None, finish_reason: str = "stop"):
    """An OpenAIBaseClient subclass that fakes _chat_completion and does NOT override invoke()."""

    class _InvokeStub(OpenAIBaseClient):
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

        async def resume(self, *args, **kwargs):
            raise NotImplementedError("stub")

        async def _chat_completion(self, **kwargs):
            if self._raise_on_completion:
                raise self._raise_on_completion
            msg = MagicMock()
            msg.content = "hello"
            msg.tool_calls = None
            choice = MagicMock()
            choice.message = msg
            choice.finish_reason = finish_reason
            resp = MagicMock()
            resp.choices = [choice]
            resp.usage = MagicMock(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            )
            return resp

    stub = _InvokeStub()
    # `self.client` must be truthy or invoke() raises at openai_base.py:1597
    # before any event is emitted. This stub deliberately disables the real
    # `_ensure_client()` (no real SDK involved), so the per-loop client cache
    # is populated directly here, the same way `_ensure_client()` itself
    # would, rather than exercising the disabled path.
    loop = asyncio.get_event_loop()
    stub._clients_by_loop[id(loop)] = _LoopClientEntry(client=MagicMock(), loop_ref=weakref.ref(loop))
    return stub


def _make_finalize(*, response_prompt_tokens: int = 7, response_completion_tokens: int = 3):
    """Return an async ``_finalize_budgeted_chat`` override matching openai_base.py:286."""

    async def _fake_finalize(
        self, messages, *, model_str, args, all_tool_calls, pending_tool_calls, partial_text, stream
    ):
        msg = MagicMock()
        msg.content = "finalized"
        msg.tool_calls = None
        choice = MagicMock()
        choice.message = msg
        choice.finish_reason = "stop"
        resp = MagicMock()
        resp.choices = [choice]
        resp.usage = MagicMock(
            prompt_tokens=response_prompt_tokens,
            completion_tokens=response_completion_tokens,
            total_tokens=response_prompt_tokens + response_completion_tokens,
        )
        return resp

    return _fake_finalize


@pytest.mark.asyncio
async def test_invoke_emits_before_and_after() -> None:
    """Normal path → one Before + one After with the provider's tokens and finish_reason."""
    client = _make_stub()
    before, before_cb = _capture()
    after, after_cb = _capture()
    client.events.subscribe(BeforeClientCallEvent, before_cb)
    client.events.subscribe(AfterClientCallEvent, after_cb)

    await client.invoke("hello", model="stub-model")

    await asyncio.sleep(0.05)  # drain emit_nowait tasks
    assert len(before) == 1
    assert len(after) == 1
    assert after[0].input_tokens == 10
    assert after[0].output_tokens == 5
    assert after[0].finish_reason == "stop"
    assert after[0].model == "stub-model"
    assert after[0].duration_ms > 0


@pytest.mark.asyncio
async def test_invoke_error_emits_failed_not_after() -> None:
    """_chat_completion raises → one Failed (error_type "RuntimeError"), no After, InvokeError."""
    client = _make_stub(raise_on_completion=RuntimeError("model on fire"))
    failed, failed_cb = _capture()
    after, after_cb = _capture()
    client.events.subscribe(ClientCallFailedEvent, failed_cb)
    client.events.subscribe(AfterClientCallEvent, after_cb)

    with pytest.raises(InvokeError):
        await client.invoke("hello", model="stub-model")

    await asyncio.sleep(0.05)
    assert len(failed) == 1
    assert failed[0].error_type == "RuntimeError"
    assert len(after) == 0


@pytest.mark.asyncio
async def test_invoke_budget_finalize_emits_after_budget_exhausted() -> None:
    """_chat_completion raises BudgetExhausted, _finalize_budgeted_chat returns → After."""
    client = _make_stub(raise_on_completion=BudgetExhausted("work call denied"))
    client._finalize_budgeted_chat = _make_finalize().__get__(client, type(client))

    after, after_cb = _capture()
    failed, failed_cb = _capture()
    client.events.subscribe(AfterClientCallEvent, after_cb)
    client.events.subscribe(ClientCallFailedEvent, failed_cb)

    result = await client.invoke("hello", model="stub-model")

    await asyncio.sleep(0.05)
    assert len(after) == 1
    assert after[0].finish_reason == "budget_exhausted"
    assert after[0].input_tokens == 7
    assert after[0].output_tokens == 3
    assert len(failed) == 0
    assert isinstance(result, InvokeResult)
    assert result.output == "finalized"


@pytest.mark.asyncio
async def test_invoke_budget_partial_emits_after_without_tokens() -> None:
    """Both raise BudgetExhausted → After with None tokens; InvokeResult still returned."""

    async def _fake_finalize_denied(self, *args, **kwargs):
        raise BudgetExhausted("finalization also denied", report={"partial_text": "partial answer"})

    client = _make_stub(
        raise_on_completion=BudgetExhausted("work call denied", report={"partial_text": "partial answer"})
    )
    client._finalize_budgeted_chat = _fake_finalize_denied.__get__(client, type(client))

    after, after_cb = _capture()
    failed, failed_cb = _capture()
    client.events.subscribe(AfterClientCallEvent, after_cb)
    client.events.subscribe(ClientCallFailedEvent, failed_cb)

    result = await client.invoke("hello", model="stub-model")

    await asyncio.sleep(0.05)
    assert len(after) == 1
    assert after[0].input_tokens is None
    assert after[0].output_tokens is None
    assert after[0].finish_reason == "budget_exhausted"
    assert len(failed) == 0
    assert isinstance(result, InvokeResult)
    assert result.output == "partial answer"


@pytest.mark.asyncio
async def test_invoke_parse_failure_emits_after_only() -> None:
    """Truncated response + output_type → After emitted, then raises, no Failed."""

    class _Out(BaseModel):
        value: str

    client = _make_stub(finish_reason="length")

    after, after_cb = _capture()
    failed, failed_cb = _capture()
    client.events.subscribe(AfterClientCallEvent, after_cb)
    client.events.subscribe(ClientCallFailedEvent, failed_cb)

    with pytest.raises(InvokeError):
        await client.invoke("hello", model="stub-model", output_type=_Out)

    await asyncio.sleep(0.05)
    assert len(after) == 1
    assert len(failed) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["normal", "error", "finalize", "partial", "parse_error"])
async def test_invoke_exactly_one_terminal_event(scenario: str) -> None:
    """Every invoke() that reaches dispatch emits exactly one terminal event."""

    class _Out(BaseModel):
        value: str

    invoke_kwargs: dict = {}
    expect_raise = False

    if scenario == "normal":
        client = _make_stub()
    elif scenario == "error":
        client = _make_stub(raise_on_completion=RuntimeError("boom"))
        expect_raise = True
    elif scenario == "finalize":
        client = _make_stub(raise_on_completion=BudgetExhausted("work call denied"))
        client._finalize_budgeted_chat = _make_finalize().__get__(client, type(client))
    elif scenario == "partial":

        async def _fake_finalize_denied(self, *args, **kwargs):
            raise BudgetExhausted("finalization also denied", report={"partial_text": "partial"})

        client = _make_stub(raise_on_completion=BudgetExhausted("work call denied", report={"partial_text": "partial"}))
        client._finalize_budgeted_chat = _fake_finalize_denied.__get__(client, type(client))
    else:  # parse_error
        client = _make_stub(finish_reason="length")
        invoke_kwargs["output_type"] = _Out
        expect_raise = True

    after, after_cb = _capture()
    failed, failed_cb = _capture()
    client.events.subscribe(AfterClientCallEvent, after_cb)
    client.events.subscribe(ClientCallFailedEvent, failed_cb)

    if expect_raise:
        with pytest.raises(Exception):
            await client.invoke("hello", model="stub-model", **invoke_kwargs)
    else:
        await client.invoke("hello", model="stub-model", **invoke_kwargs)

    await asyncio.sleep(0.05)
    assert len(after) + len(failed) == 1
