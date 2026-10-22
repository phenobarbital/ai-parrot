"""FEAT-710 TASK-4548 — client events carry tenant and cost_usd."""

from __future__ import annotations

import pytest

from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.clients.base import AbstractClient
from parrot.core.events.lifecycle.events import AfterClientCallEvent, ClientCallFailedEvent
from parrot.observability.context import current_tenant
from parrot.observability.cost import set_shared_cost_calculator


class _Calc:
    def __init__(self, value=0.01, boom=False):
        self.value = value
        self.boom = boom
        self.calls = 0

    def cost_usd(self, *, provider, model, input_tokens, output_tokens):
        self.calls += 1
        if self.boom:
            raise RuntimeError("pricing exploded")
        return self.value


class _Events:
    def __init__(self):
        self.emitted = []

    async def emit(self, event):
        self.emitted.append(event)


class _Client:
    """Minimal double exposing only the emit helpers under test."""

    _emit_after_call = AbstractClient._emit_after_call
    _emit_failed_call = AbstractClient._emit_failed_call
    _compute_call_cost = AbstractClient._compute_call_cost

    def __init__(self):
        import logging

        self.events = _Events()
        self.logger = logging.getLogger("test")

    async def _forward_to_global_awaited(self, event):
        return None


@pytest.fixture(autouse=True)
def _reset_shared():
    set_shared_cost_calculator(None)
    yield
    set_shared_cost_calculator(None)


@pytest.mark.asyncio
async def test_after_call_has_tenant_and_cost() -> None:
    calc = _Calc(0.01)
    set_shared_cost_calculator(calc)
    client = _Client()
    token = current_tenant.set("t1")
    try:
        cost = await client._emit_after_call(
            TraceContext.new_root(), client_name="openai", model="gpt-4o", duration_ms=1.0,
            input_tokens=5, output_tokens=2,
        )
    finally:
        current_tenant.reset(token)
    event = client.events.emitted[0]
    assert isinstance(event, AfterClientCallEvent)
    assert event.tenant == "t1"
    assert event.cost_usd == 0.01
    assert cost == 0.01
    assert calc.calls == 1


@pytest.mark.asyncio
async def test_no_calculator_gives_none_and_raising_calculator_never_breaks() -> None:
    client = _Client()
    tc = TraceContext.new_root()
    assert await client._emit_after_call(tc, client_name="openai", model="m", duration_ms=1.0) is None
    assert client.events.emitted[0].cost_usd is None

    set_shared_cost_calculator(_Calc(boom=True))
    assert await client._emit_after_call(tc, client_name="openai", model="m", duration_ms=1.0) is None
    assert client.events.emitted[1].cost_usd is None


@pytest.mark.asyncio
async def test_failed_call_has_tenant() -> None:
    client = _Client()
    token = current_tenant.set("t2")
    try:
        await client._emit_failed_call(
            TraceContext.new_root(), client_name="openai", model="m", duration_ms=1.0, exc=ValueError("x")
        )
    finally:
        current_tenant.reset(token)
    event = client.events.emitted[0]
    assert isinstance(event, ClientCallFailedEvent)
    assert event.tenant == "t2"


# --- AC-3: the cost computed once reaches the response's usage.estimated_cost ---------------------


class _Usage:
    def __init__(self, estimated_cost=None):
        self.estimated_cost = estimated_cost


class _Msg:
    def __init__(self, usage):
        self.usage = usage


@pytest.mark.asyncio
async def test_emit_after_call_publishes_last_call_cost() -> None:
    from parrot.observability.cost import last_call_cost

    set_shared_cost_calculator(_Calc(0.02))
    last_call_cost.set(None)
    await _Client()._emit_after_call(TraceContext.new_root(), client_name="openai", model="m", duration_ms=1.0)
    assert last_call_cost.get() == 0.02


def test_backfill_only_fills_none_and_never_raises() -> None:
    from parrot.observability.cost import backfill_estimated_cost, last_call_cost

    token = last_call_cost.set(0.5)
    try:
        empty, priced = _Msg(_Usage()), _Msg(_Usage(0.9))
        backfill_estimated_cost(empty)
        backfill_estimated_cost(priced)
        backfill_estimated_cost(object())  # no usage attribute
        assert empty.usage.estimated_cost == 0.5
        assert priced.usage.estimated_cost == 0.9
    finally:
        last_call_cost.reset(token)


@pytest.mark.asyncio
async def test_execute_llm_call_backfills_estimated_cost() -> None:
    from parrot.bots.abstract import AbstractBot

    set_shared_cost_calculator(_Calc(0.03))
    client = _Client()
    usage = _Usage()

    async def _ask(**_kwargs):
        await client._emit_after_call(TraceContext.new_root(), client_name="openai", model="m", duration_ms=1.0)
        return _Msg(usage)

    client.ask = _ask
    response = await AbstractBot.execute_llm_call(object(), client, "ask")
    assert response.usage.estimated_cost == 0.03
