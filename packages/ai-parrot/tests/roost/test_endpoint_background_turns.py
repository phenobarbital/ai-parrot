"""Agent turns run off the carrier consumer (FEAT-828, ``issue:a409d14b8130``).

Every carrier delivers one message at a time per address. A woken agent that opens its own onward
Roost conversation therefore used to wait for a reply that could only arrive on the consumer it was
holding — always ``TIMEOUT``. These tests pin the fix on real endpoints over one ``InProcessCarrier``.
"""

import asyncio
import logging
import time
from typing import Callable, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.roost import (
    AgentAddress,
    CarrierKind,
    GatingDispatcher,
    GrantPolicy,
    HandlerRegistry,
    InProcessCarrier,
    ProtocolEngine,
    RoostAgentConfig,
    RoostEndpoint,
)
from parrot.roost.directory import InterAgentGrant
from parrot.roost.endpoint import RoostFailure
from parrot.roost.performatives import FailureCode, Performative
from parrot.roost.protocols import TerminalState

HOP_LIMIT = 8


def _config(name: str) -> RoostAgentConfig:
    """A config that may be queried, may query anyone, and advertises one capability."""
    return RoostAgentConfig(capabilities=[f"{name}.answer"], grant=InterAgentGrant(scopes=["*"]))


def _endpoint(
    name: str,
    carrier: InProcessCarrier,
    wake: Optional[Callable] = None,
    *,
    config: Optional[RoostAgentConfig] = None,
    tool_manager: Optional[MagicMock] = None,
) -> RoostEndpoint:
    """Build one real endpoint sharing *carrier* (same wiring as the gate tests)."""
    engine = ProtocolEngine(default_hop_limit=HOP_LIMIT)
    cfg = config or _config(name)
    dispatcher = GatingDispatcher(
        self_name=name, config=cfg, engine=engine, handlers=HandlerRegistry(), grant=GrantPolicy()
    )
    manager = tool_manager or MagicMock()
    if tool_manager is None:
        manager.execute_tool = AsyncMock(return_value={"ok": True})
    return RoostEndpoint(
        agent_name=name,
        config=cfg,
        engine=engine,
        dispatcher=dispatcher,
        carriers={CarrierKind.IN_PROCESS: carrier},
        tool_manager=manager,
        wake=wake,
        permission_context=object(),
        sweep_interval=0,
    )


async def _start(*endpoints: RoostEndpoint) -> None:
    for endpoint in endpoints:
        await endpoint.start()


async def _stop(carrier: InProcessCarrier, *endpoints: RoostEndpoint) -> None:
    for endpoint in endpoints:
        await endpoint.stop()
    await carrier.close()


async def _drain(carrier: InProcessCarrier, *endpoints: RoostEndpoint) -> None:
    """Yield until every queue is empty and every spawned turn has finished."""
    for _ in range(200):
        if all(carrier.pending(e.agent_name) == 0 and e.turns_in_flight == 0 for e in endpoints):
            break
        await asyncio.sleep(0.001)
    await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_woken_agent_can_make_an_onward_query() -> None:
    """AC-1: A -> B -> C where B's wake queries C; A gets the composed answer well inside the timeout."""
    carrier = InProcessCarrier()

    async def wake_c(msg, dispatch):
        return msg.reply(Performative.INFORM, content=f"c:{msg.content}")

    async def wake_b(msg, dispatch):
        answer = await b.query(msg.content, receiver=AgentAddress(name="c"), timeout=2.0, hops=msg.hops)
        return msg.reply(Performative.INFORM, content=f"b:{answer}")

    a = _endpoint("a", carrier)
    b = _endpoint("b", carrier, wake_b)
    c = _endpoint("c", carrier, wake_c)
    await _start(a, b, c)
    try:
        started = time.monotonic()
        answer = await a.query("q", receiver=AgentAddress(name="b"), timeout=2.0)
        elapsed = time.monotonic() - started
        assert answer == "b:c:q"
        assert elapsed < 1.0, f"nested query took {elapsed:.2f}s — the consumer was blocked"
        await _drain(carrier, a, b, c)
        assert b.metrics["turns_started"] == 1 and c.metrics["turns_started"] == 1
        assert b.turns_in_flight == 0 and c.turns_in_flight == 0
    finally:
        await _stop(carrier, a, b, c)


@pytest.mark.asyncio
async def test_mutual_forwarding_chain_ends_in_hop_limit_not_timeout() -> None:
    """AC-2: A <-> B forwarding each other's question ends with ``HOP_LIMIT`` at the originator, promptly."""
    carrier = InProcessCarrier()

    def _forwarder(own: str, peer: str):
        async def wake(msg, dispatch):
            try:
                answer = await endpoints[own].query(
                    msg.content, receiver=AgentAddress(name=peer), timeout=2.0, hops=msg.hops
                )
            except RoostFailure as exc:
                return msg.reply(Performative.FAILURE, failure=exc.failure)
            return msg.reply(Performative.INFORM, content=answer)

        return wake

    endpoints = {
        "a": _endpoint("a", carrier, _forwarder("a", "b")),
        "b": _endpoint("b", carrier, _forwarder("b", "a")),
    }
    await _start(*endpoints.values())
    try:
        started = time.monotonic()
        with pytest.raises(RoostFailure) as info:
            await endpoints["a"].query("ping", receiver=AgentAddress(name="b"), timeout=2.0)
        elapsed = time.monotonic() - started
        assert info.value.failure.code is FailureCode.HOP_LIMIT
        assert elapsed < 1.0, f"chain took {elapsed:.2f}s — it was ended by timeouts, not the hop limit"
        await _drain(carrier, *endpoints.values())
        wakes = sum(e.metrics["wakes"] for e in endpoints.values())
        assert 0 < wakes <= HOP_LIMIT + 1
        assert all(e.turns_in_flight == 0 for e in endpoints.values())
    finally:
        await _stop(carrier, *endpoints.values())


@pytest.mark.asyncio
async def test_failing_wake_is_logged_and_the_next_message_is_still_served(caplog: pytest.LogCaptureFixture) -> None:
    """AC-3: a raising turn is logged by the endpoint and does not take the consumer down."""
    carrier = InProcessCarrier()
    calls: list[str] = []

    async def wake_b(msg, dispatch):
        calls.append(str(msg.content))
        if msg.content == "boom":
            raise RuntimeError("wake exploded")
        return msg.reply(Performative.INFORM, content="fine")

    a = _endpoint("a", carrier)
    b = _endpoint("b", carrier, wake_b)
    await _start(a, b)
    try:
        with caplog.at_level(logging.ERROR, logger="parrot.roost.endpoint"):
            await a.inform(receivers=[AgentAddress(name="b")], content="boom")
            await _drain(carrier, a, b)
        assert calls == ["boom"]
        assert any("Roost turn for b" in record.getMessage() for record in caplog.records)
        assert b.turns_in_flight == 0
        answer = await a.query("again", receiver=AgentAddress(name="b"), timeout=2.0)
        assert answer == "fine"
        assert calls == ["boom", "again"]
    finally:
        await _stop(carrier, a, b)


@pytest.mark.asyncio
async def test_stop_cancels_an_in_flight_turn_and_closes_its_conversation() -> None:
    """AC-4: ``stop()`` cancels a turn blocked on its own onward query instead of waiting it out."""
    carrier = InProcessCarrier()
    saw_cancel = asyncio.Event()

    async def wake_c(msg, dispatch):
        await asyncio.sleep(10)
        return None

    async def wake_b(msg, dispatch):
        try:
            await b.query("slow", receiver=AgentAddress(name="c"), timeout=5.0, conversation_id="nested-1")
        except asyncio.CancelledError:
            saw_cancel.set()
            raise
        return None

    a = _endpoint("a", carrier)
    b = _endpoint("b", carrier, wake_b)
    c = _endpoint("c", carrier, wake_c)
    await _start(a, b, c)
    try:
        await a.inform(receivers=[AgentAddress(name="b")], content="go")
        for _ in range(200):
            if b.turns_in_flight == 1 and c.turns_in_flight == 1:
                break
            await asyncio.sleep(0.001)
        assert b.turns_in_flight == 1, "the wake should be in flight, waiting on its onward query"
        started = time.monotonic()
        await b.stop()
        assert time.monotonic() - started < 1.0
        assert saw_cancel.is_set()
        assert b.turns_in_flight == 0
        state = b.engine.state("nested-1")
        assert state is not None and state.terminal is TerminalState.CANCELLED
    finally:
        await _stop(carrier, a, b, c)
    assert c.turns_in_flight == 0


@pytest.mark.asyncio
async def test_serving_tool_can_query_a_third_agent() -> None:
    """AC-5: a ``RUN_TOOL`` turn whose tool awaits ``endpoint.query()`` completes and answers the requester."""
    carrier = InProcessCarrier()

    async def wake_c(msg, dispatch):
        return msg.reply(Performative.INFORM, content=f"c:{msg.content}")

    async def calc_sum(tool_name: str, args: dict, *, permission_context=None):
        assert tool_name == "calc_sum"
        answer = await b.query("x", receiver=AgentAddress(name="c"), timeout=2.0)
        return {"result": answer, "n": args.get("n")}

    manager = MagicMock()
    manager.execute_tool = AsyncMock(side_effect=calc_sum)
    a = _endpoint("a", carrier)
    b = _endpoint(
        "b",
        carrier,
        config=RoostAgentConfig(
            capabilities=["calc.sum"], backing="deterministic", grant=InterAgentGrant(scopes=["*"])
        ),
        tool_manager=manager,
    )
    c = _endpoint("c", carrier, wake_c)
    await _start(a, b, c)
    try:
        started = time.monotonic()
        result = await a.request("calc.sum", {"n": 1}, receiver=AgentAddress(name="b"), timeout=2.0)
        assert time.monotonic() - started < 1.0
        assert result == {"result": "c:x", "n": 1}
        manager.execute_tool.assert_awaited_once()
        await _drain(carrier, a, b, c)
        assert b.metrics["turns_started"] == 1 and b.metrics["wakes"] == 0
    finally:
        await _stop(carrier, a, b, c)
