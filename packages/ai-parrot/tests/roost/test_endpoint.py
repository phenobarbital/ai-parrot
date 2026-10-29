"""Focused behavioural tests for the Roost endpoint."""

from unittest.mock import AsyncMock, MagicMock

import asyncio
import uuid

import pytest

from parrot.roost.carriers.inprocess import InProcessCarrier
from parrot.roost.directory import InterAgentGrant, RoostAgentConfig
from parrot.roost.endpoint import RoostEndpoint, RoostFailure
from parrot.roost.gating import GatingDispatcher, HandlerRegistry
from parrot.roost.grant import GrantPolicy
from parrot.roost.messages import AgentAddress, FailureInfo, RoostMessage
from parrot.roost.performatives import CarrierKind, FailureCode, InteractionProtocol, Performative
from parrot.roost import squawk_bridge
from parrot.roost.protocols import ProtocolEngine

GRANTED = RoostAgentConfig(grant=InterAgentGrant(scopes=["*"]))


def make_endpoint(
    name: str,
    carrier: InProcessCarrier,
    *,
    config: RoostAgentConfig | None = None,
    tool_result: object = None,
    working_memory: MagicMock | None = None,
    wake: AsyncMock | None = None,
    registry: MagicMock | None = None,
    engine: ProtocolEngine | None = None,
) -> RoostEndpoint:
    """Build an endpoint with deterministic mocks for external agent services."""
    tool_manager = MagicMock()
    tool_manager.execute_tool = AsyncMock(return_value=tool_result)
    engine = engine or ProtocolEngine()
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
    caller = make_endpoint("caller", carrier, config=GRANTED)
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
    caller = make_endpoint("caller", carrier, config=GRANTED)
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code"),
    [(RuntimeError("boom"), FailureCode.INTERNAL), (PermissionError("denied"), FailureCode.POLICY)],
)
async def test_failing_tool_yields_typed_failure_not_timeout(error: Exception, code: FailureCode) -> None:
    """A tool that raises answers with a typed failure instead of leaving the caller to time out."""
    carrier = InProcessCarrier()
    hr = make_endpoint(
        "hr", carrier, config=RoostAgentConfig(capabilities=["hr.people.salary"], backing="deterministic")
    )
    hr.tool_manager.execute_tool = AsyncMock(side_effect=error)
    caller = make_endpoint("caller", carrier, config=GRANTED)
    await hr.start()
    await caller.start()
    try:
        with pytest.raises(RoostFailure) as exc_info:
            await caller.request("hr.people.salary", {}, receiver=AgentAddress(name="hr"), timeout=2)
        assert exc_info.value.failure.code is code
    finally:
        await caller.stop()
        await hr.stop()


@pytest.mark.asyncio
async def test_request_with_receiver_outside_grant_is_denied() -> None:
    """A direct request is fail-closed against the caller's inter-agent grant (AC-12)."""
    from parrot.roost.grant import GrantDenied

    carrier = InProcessCarrier()
    caller = make_endpoint("caller", carrier, config=RoostAgentConfig(grant=InterAgentGrant(scopes=["hr.*"])))
    with pytest.raises(GrantDenied):
        await caller.request("finance.payroll", {}, receiver=AgentAddress(name="finance"), timeout=1)
    with pytest.raises(GrantDenied):
        await make_endpoint("bare", carrier).request("hr.x", {}, receiver=AgentAddress(name="hr"), timeout=1)


@pytest.mark.asyncio
async def test_hop_limit_is_enforced_on_the_wire() -> None:
    """A request seeded beyond the hop limit is answered with failure(HOP_LIMIT)."""
    carrier = InProcessCarrier()
    hr = make_endpoint("hr", carrier, config=RoostAgentConfig(capabilities=["hr.x"], backing="deterministic"))
    caller = make_endpoint("caller", carrier, config=GRANTED)
    await hr.start()
    await caller.start()
    try:
        with pytest.raises(RoostFailure) as exc_info:
            await caller.request("hr.x", {}, receiver=AgentAddress(name="hr"), timeout=2, hops=8)
        assert exc_info.value.failure.code is FailureCode.HOP_LIMIT
        hr.tool_manager.execute_tool.assert_not_awaited()
    finally:
        await caller.stop()
        await hr.stop()


@pytest.mark.asyncio
async def test_expired_conversation_emits_failure_timeout_to_the_requester() -> None:
    """The serving side's sweep sends failure(TIMEOUT) when a conversation passes its deadline."""
    carrier = InProcessCarrier()
    server = make_endpoint("server", carrier, config=RoostAgentConfig(capabilities=["s.x"]))
    caller = make_endpoint("caller", carrier, config=GRANTED)
    await server.start()
    await caller.start()
    try:
        with pytest.raises(RoostFailure) as exc_info:
            await caller.request("s.x", {}, receiver=AgentAddress(name="server"), timeout=0.2)
        assert exc_info.value.failure.code is FailureCode.TIMEOUT
        await asyncio.sleep(0.3)
        assert await server.sweep() >= 0
        assert caller.engine.state(next(iter(caller.engine._states))).terminal is not None
    finally:
        await caller.stop()
        await server.stop()


@pytest.mark.asyncio
async def test_hop_limit_on_the_caller_side_fails_the_query_instead_of_returning_a_result() -> None:
    """A reply that trips the caller's own hop limit raises HOP_LIMIT, never a result."""
    carrier = InProcessCarrier()

    async def wake(msg, dispatch):
        return msg.reply(Performative.INFORM, content={"answer": 42})

    srv = make_endpoint(
        "srv",
        carrier,
        config=RoostAgentConfig(capabilities=["s.x"]),
        wake=wake,
        engine=ProtocolEngine(default_hop_limit=99),
    )
    caller = make_endpoint("caller", carrier, config=GRANTED, engine=ProtocolEngine(default_hop_limit=4))
    await srv.start()
    await caller.start()
    try:
        with pytest.raises(RoostFailure) as exc_info:
            await caller.query("how much?", receiver=AgentAddress(name="srv"), timeout=2, hops=5)
        assert exc_info.value.failure.code is FailureCode.HOP_LIMIT
    finally:
        await caller.stop()
        await srv.stop()


@pytest.mark.asyncio
async def test_hop_limit_on_the_caller_side_fails_the_request_instead_of_timing_out() -> None:
    """The REQUEST path surfaces HOP_LIMIT, not the TIMEOUT it used to degrade into."""
    carrier = InProcessCarrier()
    hr = make_endpoint(
        "hr",
        carrier,
        config=RoostAgentConfig(capabilities=["hr.x"], backing="deterministic"),
        tool_result={"salary": 100},
        engine=ProtocolEngine(default_hop_limit=99),
    )
    caller = make_endpoint("caller", carrier, config=GRANTED, engine=ProtocolEngine(default_hop_limit=4))
    await hr.start()
    await caller.start()
    try:
        with pytest.raises(RoostFailure) as exc_info:
            await caller.request("hr.x", {}, receiver=AgentAddress(name="hr"), timeout=2, hops=5)
        assert exc_info.value.failure.code is FailureCode.HOP_LIMIT
    finally:
        await caller.stop()
        await hr.stop()


async def _open_budgeted_query(caller: RoostEndpoint, target: str, *, token_budget: int) -> str:
    """Send a QUERY whose envelope declares ``token_budget`` and return its conversation id."""
    conversation_id = uuid.uuid4().hex
    envelope = squawk_bridge.new_envelope(
        correlation_id=conversation_id,
        caller=caller.agent_name,
        token_budget=token_budget,
    )
    await caller.send(
        Performative.QUERY,
        receivers=[AgentAddress(name=target)],
        content="how much?",
        protocol=InteractionProtocol.QUERY,
        conversation_id=conversation_id,
        envelope=envelope,
    )
    return conversation_id


@pytest.mark.asyncio
async def test_wake_reported_tokens_trip_the_conversation_token_budget() -> None:
    """A wake response carrying `tokens` beyond the budget closes with TOKEN_BUDGET."""
    carrier = InProcessCarrier()

    async def wake(msg, dispatch):
        return msg.reply(Performative.INFORM, content={"answer": 42}, tokens=50)

    srv = make_endpoint("srv", carrier, config=RoostAgentConfig(capabilities=["s.x"]), wake=wake)
    caller = make_endpoint("caller", carrier, config=GRANTED)
    await srv.start()
    await caller.start()
    try:
        conversation_id = await _open_budgeted_query(caller, "srv", token_budget=10)
        await asyncio.sleep(0.1)
        state = srv.engine.state(conversation_id)
        assert state is not None
        assert state.budget.tokens_used == 50
        assert state.terminal is not None
    finally:
        await caller.stop()
        await srv.stop()


@pytest.mark.asyncio
async def test_budgeted_conversation_warns_once_when_wake_reports_no_tokens(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A budgeted conversation whose wake reports 0 tokens warns once and still serves."""
    carrier = InProcessCarrier()

    async def wake(msg, dispatch):
        return msg.reply(Performative.INFORM, content={"answer": 42})

    srv = make_endpoint("srv", carrier, config=RoostAgentConfig(capabilities=["s.x"]), wake=wake)
    caller = make_endpoint("caller", carrier, config=GRANTED)
    await srv.start()
    await caller.start()
    try:
        with caplog.at_level("WARNING", logger=srv.logger.name):
            conversation_id = await _open_budgeted_query(caller, "srv", token_budget=10)
            await asyncio.sleep(0.1)
        warnings = [r for r in caplog.records if conversation_id in r.getMessage()]
        assert len(warnings) == 1, f"expected exactly one warning, got {len(warnings)}"
        assert srv.engine.state(conversation_id).budget.tokens_used == 0

        # The dedupe set itself: repeated 0-token turns on a conversation that is still
        # open warn exactly once. The end-to-end turn above cannot show this, because a
        # QUERY reaches its terminal on the first INFORM.
        caplog.clear()
        open_id = uuid.uuid4().hex
        opener = RoostMessage(
            performative=Performative.QUERY,
            protocol=InteractionProtocol.QUERY,
            conversation_id=open_id,
            sender=AgentAddress(name="caller"),
            receivers=[AgentAddress(name="srv")],
            content="still open",
            envelope=squawk_bridge.new_envelope(
                correlation_id=open_id, caller="caller", token_budget=10
            ),
        )
        srv.engine.open(opener)
        with caplog.at_level("WARNING", logger=srv.logger.name):
            srv._warn_unfed_token_budget(open_id)
            srv._warn_unfed_token_budget(open_id)
        assert len([r for r in caplog.records if open_id in r.getMessage()]) == 1
    finally:
        await caller.stop()
        await srv.stop()


@pytest.mark.asyncio
async def test_unbudgeted_conversation_does_not_warn_about_tokens(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A conversation with no token budget is legitimately unbudgeted and stays silent."""
    carrier = InProcessCarrier()

    async def wake(msg, dispatch):
        return msg.reply(Performative.INFORM, content={"answer": 42})

    srv = make_endpoint("srv", carrier, config=RoostAgentConfig(capabilities=["s.x"]), wake=wake)
    caller = make_endpoint("caller", carrier, config=GRANTED)
    await srv.start()
    await caller.start()
    try:
        with caplog.at_level("WARNING", logger=srv.logger.name):
            result = await caller.query("how much?", receiver=AgentAddress(name="srv"), timeout=2)
        assert result == {"answer": 42}
        assert not [r for r in caplog.records if "token budget" in r.getMessage()]
    finally:
        await caller.stop()
        await srv.stop()
