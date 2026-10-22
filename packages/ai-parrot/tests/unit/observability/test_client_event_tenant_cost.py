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
