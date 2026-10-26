"""Tests for the in-process Roost carrier (FEAT-747 TASK-4720)."""
import asyncio

import pytest

from parrot.roost.carriers import InProcessCarrier as LazyInProcess
from parrot.roost.carriers.base import CarrierClosed, Undeliverable
from parrot.roost.carriers.inprocess import InProcessCarrier
from parrot.roost.messages import AgentAddress, RoostMessage
from parrot.roost.performatives import InteractionProtocol as IP, Performative as P


def _msg(receivers, content=None, cap=None):
    return RoostMessage(
        performative=P.INFORM, protocol=IP.INFORM, conversation_id="c",
        sender=AgentAddress(name="a"), receivers=[AgentAddress(name=n) for n in receivers],
        content=content, capability_filter=cap,
    )


@pytest.mark.asyncio
async def test_by_reference():
    c, got, payload = InProcessCarrier(), asyncio.Queue(), object()
    await c.subscribe(AgentAddress(name="b"), got.put)
    sent = _msg(["b"], payload)
    await c.send(sent)
    received = await asyncio.wait_for(got.get(), 1)
    assert received.content is payload
    assert received is sent
    await c.close()


@pytest.mark.asyncio
async def test_unknown_receiver():
    c = InProcessCarrier()
    with pytest.raises(Undeliverable):
        await c.send(_msg(["zz"]))
    await c.close()


@pytest.mark.asyncio
async def test_capability_broadcast():
    c = InProcessCarrier()
    q1, q2 = asyncio.Queue(), asyncio.Queue()
    await c.subscribe(AgentAddress(name="b"), q1.put, capabilities=["code.review"])
    await c.subscribe(AgentAddress(name="d"), q2.put, capabilities=["billing"])
    await c.send(_msg([], cap="code.*"))
    assert (await asyncio.wait_for(q1.get(), 1)).capability_filter == "code.*"
    await asyncio.sleep(0.05)
    assert q2.empty()
    with pytest.raises(Undeliverable):
        await c.send(_msg([], cap="nomatch*"))
    await c.close()


@pytest.mark.asyncio
async def test_close_and_unsubscribe_and_consumer_survives():
    c = InProcessCarrier()
    seen = []

    async def handler(m):
        seen.append(m)
        if len(seen) == 1:
            raise RuntimeError("boom")

    sid = await c.subscribe(AgentAddress(name="b"), handler)
    await c.send(_msg(["b"]))
    await c.send(_msg(["b"]))
    for _ in range(50):
        if len(seen) == 2:
            break
        await asyncio.sleep(0.01)
    assert len(seen) == 2
    assert await c.unsubscribe(sid) is True
    assert await c.unsubscribe(sid) is False
    await c.close()
    with pytest.raises(CarrierClosed):
        await c.send(_msg(["b"]))


def test_lazy_export():
    assert LazyInProcess is InProcessCarrier
