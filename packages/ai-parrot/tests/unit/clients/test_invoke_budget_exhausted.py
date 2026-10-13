"""Direct tests for OpenAIBaseClient.invoke() budget-exhausted control flow (FEAT-662).

These tests assert only on the returned ``InvokeResult`` / raised errors and the
call sequence — never on lifecycle telemetry (covered by FEAT-579).
"""

from __future__ import annotations

import asyncio
import weakref
from unittest.mock import MagicMock

import pytest

from parrot.clients.base import _LoopClientEntry
from parrot.clients.openai_base import OpenAIBaseClient
from parrot.core.exceptions import BudgetExhausted
from parrot.models.responses import InvokeResult


def _make_stub(*, work_error: Exception, finalize_error: Exception | None = None):
    """Stub whose work call always raises ``work_error`` and records finalize calls."""

    class _Stub(OpenAIBaseClient):
        client_name = "stub-openai"
        client_type = "stub"
        model = "stub-model"

        def __init__(self):
            super().__init__(debug=False)
            self.chat_calls = 0
            self.finalize_calls = 0

        async def get_client(self):
            return MagicMock()

        async def _ensure_client(self):
            pass

        async def resume(self, *args, **kwargs):
            raise NotImplementedError("stub")

        async def _chat_completion(self, **kwargs):
            self.chat_calls += 1
            raise work_error

        async def _finalize_budgeted_chat(self, messages, **kwargs):
            self.finalize_calls += 1
            if finalize_error is not None:
                raise finalize_error
            msg = MagicMock()
            msg.content = "finalized answer"
            msg.tool_calls = None
            choice = MagicMock()
            choice.message = msg
            choice.finish_reason = "stop"
            resp = MagicMock()
            resp.choices = [choice]
            resp.usage = MagicMock(prompt_tokens=7, completion_tokens=3, total_tokens=10)
            return resp

    stub = _Stub()
    loop = asyncio.get_event_loop()
    stub._clients_by_loop[id(loop)] = _LoopClientEntry(client=MagicMock(), loop_ref=weakref.ref(loop))
    return stub


@pytest.mark.asyncio
async def test_budget_exhausted_finalize_path_returns_finalized_output() -> None:
    """Work call denied, finalization succeeds: the finalized text is returned."""
    client = _make_stub(work_error=BudgetExhausted("work call denied"))

    result = await client.invoke("hello", model="stub-model")

    assert isinstance(result, InvokeResult)
    assert result.output == "finalized answer"
    assert client.chat_calls == 1
    assert client.finalize_calls == 1


@pytest.mark.asyncio
async def test_budget_exhausted_partial_bx2_path_returns_partial_text() -> None:
    """Work and finalization both denied: the partial text is returned, no error raised."""
    client = _make_stub(
        work_error=BudgetExhausted("work call denied"),
        finalize_error=BudgetExhausted("finalization denied", report={"partial_text": "partial answer"}),
    )

    result = await client.invoke("hello", model="stub-model")

    assert isinstance(result, InvokeResult)
    assert result.output == "partial answer"
    assert result.raw_response is None
    assert client.finalize_calls == 1


@pytest.mark.asyncio
async def test_budget_exhausted_bx2_without_partial_text_returns_empty_output() -> None:
    """bx2 report lacking partial_text degrades to an empty output."""
    client = _make_stub(
        work_error=BudgetExhausted("work call denied"),
        finalize_error=BudgetExhausted("finalization denied"),
    )

    result = await client.invoke("hello", model="stub-model")

    assert result.output == ""
