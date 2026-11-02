"""LocalEnvelope query traces, generated failures, and audit-race regressions for FEAT-790."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.core.events.lifecycle import TraceContext
from parrot.roost import squawk_bridge
from parrot.roost.audit import RoostAuditLedger
from parrot.roost.carriers.inprocess import InProcessCarrier
from parrot.roost.directory import InterAgentGrant, RoostAgentConfig
from parrot.roost.endpoint import RoostEndpoint, RoostFailure
from parrot.roost.gating import GatingDispatcher, HandlerRegistry
from parrot.roost.grant import GrantPolicy
from parrot.roost.messages import AgentAddress, FailureInfo, LocalEnvelope, RoostMessage
from parrot.roost.performatives import CarrierKind, FailureCode, InteractionProtocol, Performative
from parrot.roost.protocols import ConversationBudget, ProtocolEngine, TerminalState


GRANTED = RoostAgentConfig(grant=InterAgentGrant(scopes=["*"]))
CALLER_CONTEXT = object()


def make_endpoint(
    name: str,
    carrier: InProcessCarrier,
    *,
    config: RoostAgentConfig | None = None,
    engine: ProtocolEngine | None = None,
    ledger: RoostAuditLedger | None = None,
    wake: object = None,
) -> RoostEndpoint:
    """Build an isolated endpoint using the real dispatcher, carrier, and audit ledger."""
    selected_engine = engine or ProtocolEngine()
    dispatcher = GatingDispatcher(
        self_name=name,
        config=config,
        engine=selected_engine,
        handlers=HandlerRegistry(),
        grant=GrantPolicy(),
    )
    tool_manager = MagicMock()
    tool_manager.execute_tool = AsyncMock()
    return RoostEndpoint(
        agent_name=name,
        config=config,
        engine=selected_engine,
        dispatcher=dispatcher,
        carriers={CarrierKind.IN_PROCESS: carrier},
        tool_manager=tool_manager,
        ledger=ledger,
        wake=wake,
        permission_context=CALLER_CONTEXT,
        sweep_interval=0,
    )


def opener(
    conversation_id: str,
    *,
    sender: str = "caller",
    receiver: str = "server",
    envelope: LocalEnvelope | None = None,
    hops: int = 0,
) -> RoostMessage:
    """Create a Query opener for deterministic engine tests."""
    return RoostMessage(
        performative=Performative.QUERY,
        protocol=InteractionProtocol.QUERY,
        conversation_id=conversation_id,
        sender=AgentAddress(name=sender),
        receivers=[AgentAddress(name=receiver)],
        content="question",
        envelope=envelope or LocalEnvelope(correlation_id=conversation_id, caller=sender),
        hops=hops,
    )


@pytest.fixture(autouse=True)
def force_local_envelopes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every assertion qualified to Roost's built-in LocalEnvelope."""
    monkeypatch.setattr(squawk_bridge, "squawk_available", lambda: False)


@pytest.mark.asyncio
async def test_query_trace_exchange() -> None:
    """Both ledgers retain the exact trace and valid signatures on opener and reply."""
    carrier = InProcessCarrier()

    async def wake(msg: RoostMessage, _dispatch: object) -> RoostMessage:
        return msg.reply(Performative.INFORM, content={"answer": 42})

    server = make_endpoint("analyst", carrier, wake=wake)
    caller = make_endpoint("caller", carrier, config=GRANTED)
    await server.start()
    await caller.start()
    try:
        result = await caller.query("revenue?", receiver=AgentAddress(name="analyst"), trace_id="t1", timeout=1)
        assert result == {"answer": 42}
        assert server.metrics["wakes"] == 1
        assert caller.metrics["wakes"] == 0
        for endpoint, direction in ((caller, "received"), (server, "served")):
            entries = endpoint.ledger.entries(trace_id="t1")
            assert [entry.performative for entry in entries] == [Performative.QUERY, Performative.INFORM]
            assert {entry.direction for entry in entries} == {direction}
            assert all([await endpoint.ledger.verify(entry) for entry in entries])
    finally:
        await caller.stop()
        await server.stop()


@pytest.mark.asyncio
async def test_invalid_trace_has_no_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """All invalid values raise before state, envelope creation, waiter creation, or send."""
    endpoint = make_endpoint("caller", InProcessCarrier(), config=GRANTED)
    envelope_factory = MagicMock(wraps=squawk_bridge.new_envelope)
    monkeypatch.setattr(squawk_bridge, "new_envelope", envelope_factory)
    invalid_values: list[object] = [1, "", " ", "a\u00a0b", "a\nb", "a\u200db"]
    for value in invalid_values:
        with pytest.raises(ValueError):
            await endpoint.query("question", receiver=AgentAddress(name="analyst"), trace_id=value)  # type: ignore[arg-type]
    assert envelope_factory.call_count == 0
    assert endpoint.engine._states == {}
    assert endpoint._pending == {}

    async def resolve_send(*_args: object, **_kwargs: object) -> None:
        next(iter(endpoint._pending.values())).set_result("answer")

    monkeypatch.setattr(endpoint, "send", resolve_send)
    assert await endpoint.query("question", receiver=AgentAddress(name="analyst"), trace_id="t1") == "answer"
    traced_state = list(endpoint.engine._states.values())[-1]
    assert traced_state.envelope.trace.trace_id == "t1"
    assert len(traced_state.envelope.trace.span_id) == 16
    assert await endpoint.query("question", receiver=AgentAddress(name="analyst"), trace_id=None) == "answer"
    assert list(endpoint.engine._states.values())[-1].envelope.trace is None


def test_engine_terminal_retains_envelope() -> None:
    """Expiry, hop/token budget, and cancellation output retain the opener envelope."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    trace = TraceContext(trace_id="engine-trace", span_id="0123456789abcdef")
    envelope = LocalEnvelope(correlation_id="expiry", caller="caller", trace=trace, budget_ms=10)

    expiry_engine = ProtocolEngine(clock=lambda: now)
    expiry_engine.open(opener("expiry", envelope=envelope))
    expired = expiry_engine.expire(now=now + timedelta(milliseconds=11))[0].emit[0]
    assert expired.envelope == envelope
    assert expired.failure == FailureInfo(code=FailureCode.TIMEOUT, detail="conversation deadline exceeded")

    hop_engine = ProtocolEngine(default_hop_limit=1)
    hop_message = opener("hop", envelope=envelope, hops=2)
    hop_engine.open(hop_message)
    hop_failure = hop_engine.check_hops(hop_message)
    assert hop_failure is not None
    assert hop_failure.emit[0].envelope == envelope
    assert hop_failure.emit[0].failure.code is FailureCode.HOP_LIMIT

    token_engine = ProtocolEngine()
    token_message = opener(
        "token",
        envelope=LocalEnvelope(correlation_id="token", caller="caller", trace=trace, token_budget=1),
    )
    token_engine.open(token_message)
    token_failure = token_engine.charge("token", 2)
    assert token_failure is not None
    assert token_failure.emit[0].envelope == token_message.envelope
    assert token_failure.emit[0].failure.code is FailureCode.TOKEN_BUDGET

    cancel_engine = ProtocolEngine()
    cancel_message = opener("cancel", envelope=envelope)
    cancel_engine.open(cancel_message)
    cancelled = cancel_engine.close("cancel", TerminalState.CANCELLED, reason="stop").emit[0]
    assert cancelled.envelope == envelope
    assert cancelled.performative is Performative.REJECT
    assert cancelled.failure == FailureInfo(code=FailureCode.CANCELLED, detail="stop")


@pytest.mark.asyncio
async def test_query_local_and_swept_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local wait and local sweep produce traced terminal audit records and clean waiters."""
    endpoint = make_endpoint("caller", InProcessCarrier(), config=GRANTED)
    monkeypatch.setattr(endpoint, "send", AsyncMock(return_value=None))
    with pytest.raises(RoostFailure) as error:
        await endpoint.query("question", receiver=AgentAddress(name="analyst"), trace_id="local-timeout", timeout=0)
    assert error.value.failure.code is FailureCode.TIMEOUT
    assert endpoint._pending == {}
    state = next(iter(endpoint.engine._states.values()))
    assert state.terminal is TerminalState.TIMED_OUT
    entries = endpoint.ledger.entries(trace_id="local-timeout")
    assert len(entries) == 1
    assert entries[0].performative is Performative.FAILURE
    assert await endpoint.ledger.verify(entries[0])

    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    sweep_endpoint = make_endpoint(
        "caller",
        InProcessCarrier(),
        config=GRANTED,
        engine=ProtocolEngine(clock=lambda: now[0]),
    )
    sweep_envelope = LocalEnvelope(
        correlation_id="swept",
        caller="caller",
        trace=TraceContext(trace_id="swept-timeout", span_id="fedcba9876543210"),
        budget_ms=10,
    )
    sweep_endpoint.engine.open(opener("swept", receiver="analyst", envelope=sweep_envelope))
    future = asyncio.get_running_loop().create_future()
    sweep_endpoint._pending["swept"] = future
    now[0] += timedelta(milliseconds=11)
    assert await sweep_endpoint.sweep() == 1
    with pytest.raises(RoostFailure) as swept_error:
        await future
    assert swept_error.value.failure.code is FailureCode.TIMEOUT
    assert len(sweep_endpoint.ledger.entries(trace_id="swept-timeout")) == 1


@pytest.mark.asyncio
async def test_remote_sweep_timeout_retains_trace() -> None:
    """A serving-side sweep routes one traced failure back to the caller."""
    carrier = InProcessCarrier()
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    server = make_endpoint("server", carrier, engine=ProtocolEngine(clock=lambda: now[0]))
    caller = make_endpoint("caller", carrier, config=GRANTED)
    await server.start()
    await caller.start()
    try:
        task = asyncio.create_task(
            caller.query("question", receiver=AgentAddress(name="server"), trace_id="remote-timeout", timeout=10)
        )
        for _ in range(20):
            if server.engine._states:
                break
            await asyncio.sleep(0)
        assert server.engine._states
        now[0] += timedelta(seconds=11)
        assert await server.sweep() == 1
        with pytest.raises(RoostFailure) as error:
            await task
        assert error.value.failure.code is FailureCode.TIMEOUT
        for endpoint in (caller, server):
            terminal_entries = [
                entry
                for entry in endpoint.ledger.entries(trace_id="remote-timeout")
                if entry.performative is Performative.FAILURE
            ]
            assert len(terminal_entries) == 1
    finally:
        await caller.stop()
        await server.stop()


@pytest.mark.asyncio
async def test_query_cancellation_and_terminal_races(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit and task cancellation preserve semantics without duplicate local outcomes."""
    endpoint = make_endpoint("caller", InProcessCarrier(), config=GRANTED)
    sent = asyncio.Event()

    async def inert_send(*_args: object, **_kwargs: object) -> None:
        sent.set()

    monkeypatch.setattr(endpoint, "send", inert_send)
    explicit = asyncio.create_task(
        endpoint.query("question", receiver=AgentAddress(name="analyst"), trace_id="explicit-cancel")
    )
    await sent.wait()
    conversation_id = next(iter(endpoint._pending))
    await endpoint.cancel(conversation_id, reason="operator stopped")
    await endpoint.cancel(conversation_id, reason="duplicate")
    with pytest.raises(RoostFailure) as explicit_error:
        await explicit
    assert explicit_error.value.failure.code is FailureCode.CANCELLED
    explicit_entries = endpoint.ledger.entries(trace_id="explicit-cancel")
    assert [entry.performative for entry in explicit_entries] == [Performative.REJECT]

    sent.clear()
    cancelled_task = asyncio.create_task(
        endpoint.query("question", receiver=AgentAddress(name="analyst"), trace_id="task-cancel")
    )
    await sent.wait()
    task_conversation_id = next(iter(endpoint._pending))
    cancelled_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled_task
    assert endpoint.engine.state(task_conversation_id).terminal is TerminalState.CANCELLED
    task_entries = endpoint.ledger.entries(trace_id="task-cancel")
    assert [entry.performative for entry in task_entries] == [Performative.FAILURE]
    assert endpoint._pending == {}

    late = opener(
        "late",
        receiver="analyst",
        envelope=LocalEnvelope(correlation_id="late", caller="caller"),
    )
    endpoint.engine.open(late)
    await endpoint._finish_query_failure("late", code=FailureCode.TIMEOUT, detail="first")
    await endpoint._finish_query_failure("late", code=FailureCode.CANCELLED, detail="second")
    assert endpoint.engine.state("late").terminal is TerminalState.TIMED_OUT


@pytest.mark.asyncio
async def test_query_trace_isolation_and_existing_contracts() -> None:
    """Concurrent traces stay isolated while authority, hops, schema, and no-trace behavior remain intact."""
    carrier = InProcessCarrier()
    received: list[RoostMessage] = []

    async def wake(msg: RoostMessage, _dispatch: object) -> RoostMessage:
        received.append(msg)
        return msg.reply(Performative.INFORM, content={"answer": msg.content})

    server = make_endpoint("server", carrier, wake=wake)
    caller = make_endpoint("caller", carrier, config=GRANTED)
    await server.start()
    await caller.start()
    try:
        results = await asyncio.gather(
            caller.query("one", receiver=AgentAddress(name="server"), trace_id="run-a", timeout=1, hops=2),
            caller.query("two", receiver=AgentAddress(name="server"), trace_id="run-b", timeout=1, hops=3),
            caller.query("plain", receiver=AgentAddress(name="server"), timeout=1),
        )
        assert results == [{"answer": "one"}, {"answer": "two"}, {"answer": "plain"}]
        assert {message.envelope.trace.trace_id for message in received if message.envelope.trace} == {
            "run-a",
            "run-b",
        }
        spans = [message.envelope.trace.span_id for message in received if message.envelope.trace]
        assert len(spans) == len(set(spans)) == 2
        assert [message.hops for message in received] == [3, 4, 1]
        assert all(message.permission_context is CALLER_CONTEXT for message in received)
        untraced = [entry for entry in caller.ledger.entries() if entry.trace_id is None]
        assert [entry.performative for entry in untraced] == [Performative.QUERY, Performative.INFORM]

        with pytest.raises(RoostFailure) as schema_error:
            await caller.query(
                "schema",
                receiver=AgentAddress(name="server"),
                timeout=1,
                expected_schema={"type": "array"},
            )
        assert schema_error.value.failure.code is FailureCode.SCHEMA
    finally:
        await caller.stop()
        await server.stop()


@pytest.mark.asyncio
async def test_audit_storage_failure_fails_closed_and_cleans_waiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """A local audit storage error cannot resolve a query successfully or leak its waiter."""

    class BrokenStorage:
        async def store(self, _entry: object) -> None:
            raise RuntimeError("audit unavailable")

    endpoint = make_endpoint(
        "caller",
        InProcessCarrier(),
        config=GRANTED,
        ledger=RoostAuditLedger(storage=BrokenStorage()),
    )

    async def route_reply(*_args: object, **_kwargs: object) -> None:
        state = next(iter(endpoint.engine._states.values()))
        response = RoostMessage(
            performative=Performative.INFORM,
            protocol=InteractionProtocol.QUERY,
            conversation_id=state.conversation_id,
            sender=AgentAddress(name="server"),
            receivers=[AgentAddress(name="caller")],
            content="answer",
            envelope=state.envelope,
        )
        await endpoint._route_emitted(response)

    monkeypatch.setattr(endpoint, "send", route_reply)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await endpoint.query("question", receiver=AgentAddress(name="server"), trace_id="audit-error")
    assert endpoint._pending == {}
    assert endpoint.ledger.entries() == []
