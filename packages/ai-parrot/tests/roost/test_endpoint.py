"""Focused behavioural tests for the Roost endpoint."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.roost.carriers.inprocess import InProcessCarrier
from parrot.roost.directory import RoostAgentConfig
from parrot.roost.endpoint import RoostEndpoint, RoostFailure
from parrot.roost.gating import GatingDispatcher, HandlerRegistry
from parrot.roost.grant import GrantPolicy
from parrot.roost.messages import AgentAddress, FailureInfo
from parrot.roost.performatives import CarrierKind, FailureCode, InteractionProtocol, Performative
from parrot.roost.protocols import ProtocolEngine


def make_endpoint(
    name: str,
    carrier: InProcessCarrier,
    *,
    config: RoostAgentConfig | None = None,
    tool_result: object = None,
    working_memory: MagicMock | None = None,
    wake: AsyncMock | None = None,
    registry: MagicMock | None = None,
) -> RoostEndpoint:
    """Build an endpoint with deterministic mocks for external agent services."""
    tool_manager = MagicMock()
    tool_manager.execute_tool = AsyncMock(return_value=tool_result)
    engine = ProtocolEngine()
    dispatcher = GatingDispatcher(
        self_name=name,
        config=config,
        engine=engine,
        handlers=HandlerRegistry(),
        grant=GrantPolicy(),
    )
    return RoostEndpoint(
        agent_name=name,
        config=config,
        engine=engine,
        dispatcher=dispatcher,
        carriers={CarrierKind.IN_PROCESS: carrier},
        tool_manager=tool_manager,
        working_memory=working_memory,
        wake=wake,
        registry=registry,
    )


@pytest.mark.asyncio
async def test_request_returns_native_object_and_uses_manager_guard() -> None:
    """A deterministic request returns the tool's object by identity."""
    carrier = InProcessCarrier()
    result = {"salary": 100}
    hr = make_endpoint(
        "hr",
        carrier,
        config=RoostAgentConfig(capabilities=["hr.people.salary"], backing="deterministic"),
        tool_result=result,
    )
    caller = make_endpoint("caller", carrier)
    await hr.start()
    await caller.start()
    try:
        output = await caller.request(
            "hr.people.salary",
            {"employee_id": "E-17"},
            receiver=AgentAddress(name="hr"),
            timeout=1,
        )
        assert output is result
        hr.tool_manager.execute_tool.assert_awaited_once()
        assert hr.tool_manager.execute_tool.await_args.kwargs["permission_context"] is None
        assert len(caller.ledger.entries()) == 3
        assert len(hr.ledger.entries()) == 3
    finally:
        await caller.stop()
        await hr.stop()


@pytest.mark.asyncio
async def test_refuse_rejects_pending_request_with_typed_failure() -> None:
    """A refusal is surfaced as a RoostFailure rather than an empty response."""
    carrier = InProcessCarrier()
    caller = make_endpoint("caller", carrier)
    server = make_endpoint("server", carrier)
    await caller.start()
    await server.start()
    try:
        task = pytest.importorskip("asyncio").create_task(
            caller.request("server.work", {}, receiver=AgentAddress(name="server"), timeout=1)
        )
        await pytest.importorskip("asyncio").sleep(0)
        conversation_id = next(iter(caller._pending))
        await server.send(
            Performative.REFUSE,
            receivers=[AgentAddress(name="caller")],
            protocol=InteractionProtocol.REQUEST,
            conversation_id=conversation_id,
        )
        with pytest.raises(RoostFailure) as error:
            await task
        assert error.value.failure.code is FailureCode.POLICY
    finally:
        await caller.stop()
        await server.stop()


@pytest.mark.asyncio
async def test_addressed_inform_wakes_once() -> None:
    """A directly addressed Inform invokes the wake callback once."""
    carrier = InProcessCarrier()
    wake = AsyncMock(return_value=None)
    receiver = make_endpoint("receiver", carrier, wake=wake)
    sender = make_endpoint("sender", carrier)
    await receiver.start()
    await sender.start()
    try:
        await sender.inform(receivers=[AgentAddress(name="receiver")], content={"notice": "hello"})
        for _ in range(10):
            if wake.await_count:
                break
            await pytest.importorskip("asyncio").sleep(0)
        wake.assert_awaited_once()
        assert receiver.metrics["wakes"] == 1
    finally:
        await sender.stop()
        await receiver.stop()


@pytest.mark.asyncio
async def test_broadcast_inform_is_stored_by_reference() -> None:
    """A capability broadcast is stored as the original native object."""
    carrier = InProcessCarrier()
    memory = MagicMock()
    memory.store_result = AsyncMock()
    receiver = make_endpoint(
        "receiver",
        carrier,
        config=RoostAgentConfig(capabilities=["digest.write"]),
        working_memory=memory,
    )
    sender = make_endpoint("sender", carrier)
    content = {"status": "complete"}
    await receiver.start()
    await sender.start()
    try:
        await sender.inform(capability_filter="digest.*", content=content)
        for _ in range(10):
            if memory.store_result.await_count:
                break
            await pytest.importorskip("asyncio").sleep(0)
        memory.store_result.assert_awaited_once()
        assert memory.store_result.await_args.kwargs["data"] is content
        assert receiver.metrics["stored"] == 1
    finally:
        await sender.stop()
        await receiver.stop()


@pytest.mark.asyncio
async def test_find_and_mount_degrades_when_satellite_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Capability mounting is total when the optional Squawk satellite is absent."""
    from parrot.roost import squawk_bridge

    carrier = InProcessCarrier()
    registry = MagicMock()
    registry.find_capability.return_value = []
    endpoint = make_endpoint("caller", carrier, registry=registry)
    monkeypatch.setattr(squawk_bridge, "squawk_available", lambda: False)
    assert await endpoint.find_and_mount("hr.people.salary") == []
    registry.find_capability.assert_called_once_with("hr.people.salary", caller="caller", limit=5)
