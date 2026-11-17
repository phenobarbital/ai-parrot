"""Caller-supplied conversation ids on ``RoostEndpoint.query`` — FEAT-825 TASK-5245."""

from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.roost.carriers.inprocess import InProcessCarrier
from parrot.roost.directory import InterAgentGrant, RoostAgentConfig
from parrot.roost.endpoint import RoostEndpoint, WakeCallback
from parrot.roost.gating import GatingDispatcher, HandlerRegistry
from parrot.roost.grant import GrantPolicy
from parrot.roost.messages import AgentAddress, RoostMessage
from parrot.roost.performatives import CarrierKind, Performative
from parrot.roost.protocols import ConversationExistsError, ProtocolEngine

GRANTED = RoostAgentConfig(grant=InterAgentGrant(scopes=["*"]))
SERVER = AgentAddress(name="server")


def make_endpoint(
    name: str,
    carrier: InProcessCarrier,
    *,
    config: RoostAgentConfig | None = None,
    wake: WakeCallback | None = None,
) -> RoostEndpoint:
    """Build an isolated endpoint using the real dispatcher and carrier."""
    engine = ProtocolEngine()
    dispatcher = GatingDispatcher(
        self_name=name,
        config=config,
        engine=engine,
        handlers=HandlerRegistry(),
        grant=GrantPolicy(),
    )
    tool_manager = MagicMock()
    tool_manager.execute_tool = AsyncMock()
    return RoostEndpoint(
        agent_name=name,
        config=config,
        engine=engine,
        dispatcher=dispatcher,
        carriers={CarrierKind.IN_PROCESS: carrier},
        tool_manager=tool_manager,
        wake=wake,
        permission_context=object(),
        sweep_interval=0,
    )


@pytest.mark.asyncio
async def test_supplied_conversation_id_is_used_end_to_end() -> None:
    """The opener, the wire message and the reply all run under the caller's id."""
    carrier = InProcessCarrier()
    received: list[RoostMessage] = []

    async def wake(msg: RoostMessage, dispatch: object) -> RoostMessage:
        received.append(msg)
        return msg.reply(Performative.INFORM, content="answer")

    server = make_endpoint("server", carrier, config=RoostAgentConfig(capabilities=["s.x"]), wake=wake)
    caller = make_endpoint("caller", carrier, config=GRANTED)
    await server.start()
    await caller.start()
    try:
        answer = await caller.query("q", receiver=SERVER, timeout=2, conversation_id="c-1")
        assert answer == "answer"
        assert [msg.conversation_id for msg in received] == ["c-1"]
        state = caller.engine.state("c-1")
        assert state is not None and state.envelope.correlation_id == "c-1"
        assert caller._pending == {}
    finally:
        await caller.stop()
        await server.stop()


@pytest.mark.asyncio
async def test_omitted_conversation_id_still_mints_a_fresh_one() -> None:
    """Without the argument every query gets its own 32-hex id, as before."""
    carrier = InProcessCarrier()
    received: list[RoostMessage] = []

    async def wake(msg: RoostMessage, dispatch: object) -> RoostMessage:
        received.append(msg)
        return msg.reply(Performative.INFORM, content="answer")

    server = make_endpoint("server", carrier, config=RoostAgentConfig(capabilities=["s.x"]), wake=wake)
    caller = make_endpoint("caller", carrier, config=GRANTED)
    await server.start()
    await caller.start()
    try:
        await caller.query("one", receiver=SERVER, timeout=2)
        await caller.query("two", receiver=SERVER, timeout=2)
        ids = [msg.conversation_id for msg in received]
        assert len(set(ids)) == 2
        assert all(re.fullmatch(r"[0-9a-f]{32}", cid) for cid in ids)
    finally:
        await caller.stop()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", " ", "a b", "tab\tid", "line\nbreak", "nul\x00", "zero​width", 7, b"bytes"])
async def test_invalid_conversation_id_is_rejected_before_anything_is_sent(bad: object) -> None:
    """A malformed id raises ``ValueError``; no conversation is opened and nothing goes out."""
    carrier = InProcessCarrier()
    caller = make_endpoint("caller", carrier, config=GRANTED)
    await caller.start()
    carrier.send = AsyncMock(wraps=carrier.send)
    try:
        with pytest.raises(ValueError, match="conversation_id"):
            await caller.query("q", receiver=SERVER, timeout=1, conversation_id=bad)
        carrier.send.assert_not_awaited()
        assert caller.engine._states == {}
        assert caller._pending == {}
    finally:
        await caller.stop()


@pytest.mark.asyncio
async def test_reusing_an_open_conversation_id_fails_closed_and_spares_the_first() -> None:
    """A duplicate id raises ``ConversationExistsError``; the conversation that owns the id still resolves."""
    carrier = InProcessCarrier()
    release = asyncio.Event()

    async def wake(msg: RoostMessage, dispatch: object) -> RoostMessage:
        await release.wait()
        return msg.reply(Performative.INFORM, content="first")

    server = make_endpoint("server", carrier, config=RoostAgentConfig(capabilities=["s.x"]), wake=wake)
    caller = make_endpoint("caller", carrier, config=GRANTED)
    await server.start()
    await caller.start()
    try:
        first = asyncio.create_task(caller.query("q1", receiver=SERVER, timeout=5, conversation_id="c-dup"))
        for _ in range(200):
            if "c-dup" in caller._pending:
                break
            await asyncio.sleep(0.005)
        pending = caller._pending["c-dup"]
        carrier.send = AsyncMock(wraps=carrier.send)

        with pytest.raises(ConversationExistsError):
            await caller.query("q2", receiver=SERVER, timeout=1, conversation_id="c-dup")

        carrier.send.assert_not_awaited()
        assert caller._pending == {"c-dup": pending}
        release.set()
        assert await first == "first"
    finally:
        release.set()
        await caller.stop()
        await server.stop()
