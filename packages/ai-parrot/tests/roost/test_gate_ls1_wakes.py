"""Gate L-S1 — wakes per message in a shared channel (FEAT-747 AC-20)."""

import asyncio
from typing import Optional
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
from parrot.roost.performatives import InteractionProtocol, Performative


def _endpoint(name: str, carrier: InProcessCarrier, cfg: Optional[RoostAgentConfig], wake: AsyncMock) -> RoostEndpoint:
    """Build one endpoint sharing *carrier* with a stubbed tool manager and wake callback."""
    eng = ProtocolEngine()
    disp = GatingDispatcher(self_name=name, config=cfg, engine=eng, handlers=HandlerRegistry(), grant=GrantPolicy())
    tm = MagicMock()
    tm.execute_tool = AsyncMock(return_value={"ok": True})
    return RoostEndpoint(
        agent_name=name,
        config=cfg,
        engine=eng,
        dispatcher=disp,
        carriers={CarrierKind.IN_PROCESS: carrier},
        tool_manager=tm,
        wake=wake,
    )


async def _channel() -> tuple[InProcessCarrier, list[RoostEndpoint]]:
    """Start five endpoints on one carrier: a sender, two ``calc.*`` agents and two ``misc`` agents."""
    carrier = InProcessCarrier()
    configs = [
        RoostAgentConfig(capabilities=["sender.noop"]),
        RoostAgentConfig(capabilities=["calc.add"]),
        RoostAgentConfig(capabilities=["calc.mul"]),
        RoostAgentConfig(capabilities=["misc.one"]),
        RoostAgentConfig(capabilities=["misc.two"]),
    ]
    endpoints = [
        _endpoint(f"agent-{i}", carrier, cfg, AsyncMock(return_value=None)) for i, cfg in enumerate(configs)
    ]
    for endpoint in endpoints:
        await endpoint.start()
    return carrier, endpoints


async def _drain(carrier: InProcessCarrier, endpoints: list[RoostEndpoint]) -> None:
    """Yield until every queue is empty and in-flight handlers have run."""
    for _ in range(50):
        await asyncio.sleep(0)
    for _ in range(50):
        if all(carrier.pending(e.agent_name) == 0 for e in endpoints):
            break
        await asyncio.sleep(0.001)
    await asyncio.sleep(0.01)


def _wakes(endpoints: list[RoostEndpoint]) -> int:
    return sum(e.metrics["wakes"] for e in endpoints)


async def _stop(carrier: InProcessCarrier, endpoints: list[RoostEndpoint]) -> None:
    for endpoint in endpoints:
        await endpoint.stop()
    await carrier.close()


@pytest.mark.asyncio
async def test_addressed_request_one_wake() -> None:
    """An addressed request to one llm_backed agent wakes exactly that agent."""
    carrier, endpoints = await _channel()
    try:
        await endpoints[0].send(
            Performative.REQUEST,
            receivers=[AgentAddress(name="agent-1")],
            content={"a": 1},
            protocol=InteractionProtocol.REQUEST,
        )
        await _drain(carrier, endpoints)
        assert _wakes(endpoints) == 1
        assert endpoints[1].metrics["wakes"] == 1
    finally:
        await _stop(carrier, endpoints)


@pytest.mark.asyncio
async def test_broadcast_cfp_two_matches_two_wakes() -> None:
    """A broadcast CFP matching two llm_backed capabilities wakes exactly those two agents."""
    carrier, endpoints = await _channel()
    try:
        await endpoints[0].send(
            Performative.CFP,
            capability_filter="calc.*",
            content={"task": "sum"},
            protocol=InteractionProtocol.CONTRACT_NET,
        )
        await _drain(carrier, endpoints)
        assert _wakes(endpoints) == 2
        assert endpoints[1].metrics["wakes"] == 1
        assert endpoints[2].metrics["wakes"] == 1
    finally:
        await _stop(carrier, endpoints)


@pytest.mark.asyncio
async def test_unaddressed_inform_no_handler_zero_wakes() -> None:
    """A broadcast inform with no registered handler is stored, never woken."""
    carrier, endpoints = await _channel()
    try:
        await endpoints[0].inform(capability_filter="*", content={"notice": "hello"})
        await _drain(carrier, endpoints)
        assert _wakes(endpoints) == 0
        assert sum(e.metrics["messages_in"] for e in endpoints) == 4
    finally:
        await _stop(carrier, endpoints)
