"""Tests for the same-host shared-memory carrier (FEAT-747 M8)."""
import asyncio
from multiprocessing import shared_memory

import pandas as pd
import pytest

from parrot.roost.carriers.inprocess import InProcessCarrier
from parrot.roost.carriers.shm import SharedMemoryCarrier
from parrot.roost.messages import AgentAddress, RoostMessage
from parrot.roost.performatives import InteractionProtocol as IP, Performative as P
from parrot.tools.repl_worker.transport import StrictTransportError


def _msg(content) -> RoostMessage:
    return RoostMessage(
        performative=P.INFORM,
        protocol=IP.INFORM,
        conversation_id="c",
        sender=AgentAddress(name="a"),
        receivers=[AgentAddress(name="b")],
        content=content,
    )


def _gone(name: str) -> bool:
    try:
        shm = shared_memory.SharedMemory(name=name)
    except FileNotFoundError:
        return True
    shm.close()
    return False


async def test_roundtrip_and_unlink():
    shm = SharedMemoryCarrier(signal=InProcessCarrier())
    got: asyncio.Queue = asyncio.Queue()
    await shm.subscribe(AgentAddress(name="b"), got.put)
    df = pd.DataFrame({"a": [1, 2, 3]})
    await shm.send(_msg(df))
    out = await asyncio.wait_for(got.get(), 2)
    pd.testing.assert_frame_equal(out.content, df)
    await asyncio.sleep(0)
    assert shm._owned == {}
    await shm.close()


async def test_close_unlinks_leftovers():
    shm = SharedMemoryCarrier(signal=InProcessCarrier())
    await shm.subscribe(AgentAddress(name="b"), asyncio.Queue().put)
    # no consumer ack happens before close if we close immediately after send
    msg = _msg(pd.DataFrame({"a": [1]}))
    sent_ref = {}
    orig = shm._signal.send

    async def capture(m):
        sent_ref["ref"] = m.content  # swallow: never delivered, so never ACKed
    shm._signal.send = capture  # type: ignore[method-assign]
    await shm.send(msg)
    name = sent_ref["ref"].shm_name
    assert name in shm._owned and not _gone(name)
    await shm.close()
    assert shm._owned == {} and _gone(name)
    shm._signal.send = orig  # type: ignore[method-assign]


async def test_original_message_untouched_and_passthrough():
    shm = SharedMemoryCarrier(signal=InProcessCarrier())
    got: asyncio.Queue = asyncio.Queue()
    await shm.subscribe(AgentAddress(name="b"), got.put)
    df = pd.DataFrame({"a": [1]})
    msg = _msg(df)
    await shm.send(msg)
    assert msg.content is df
    await asyncio.wait_for(got.get(), 2)
    await shm.send(_msg({"k": 1}))
    out = await asyncio.wait_for(got.get(), 2)
    assert out.content == {"k": 1}
    await shm.close()


async def test_unencodable_frame_raises_strict():
    shm = SharedMemoryCarrier(signal=InProcessCarrier())
    await shm.subscribe(AgentAddress(name="b"), asyncio.Queue().put)
    df = pd.DataFrame({"a": [object(), object()]})
    with pytest.raises(StrictTransportError):
        await shm.send(_msg(df))
    assert shm._owned == {}
    await shm.close()
