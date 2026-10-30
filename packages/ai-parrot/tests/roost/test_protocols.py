"""Unit tests for Roost protocol state machines."""

from datetime import datetime, timedelta, timezone

import pytest

from parrot.roost.messages import AgentAddress, LocalEnvelope, RoostMessage
from parrot.roost.performatives import FailureCode, InteractionProtocol as IP, Performative as P
from parrot.roost.protocols import ConversationBudget, ProtocolEngine, TerminalState


def _envelope(*, budget_ms: int | None = None, token_budget: int | None = None) -> LocalEnvelope:
    """Build an envelope with optional conversation budgets."""
    return LocalEnvelope(correlation_id="correlation", caller="a", budget_ms=budget_ms, token_budget=token_budget)


def _msg(
    perf: P,
    proto: IP,
    cid: str = "c1",
    sender: str = "a",
    to: str = "b",
    envelope: LocalEnvelope | None = None,
    **kwargs: object,
) -> RoostMessage:
    """Build a direct Roost message for a protocol test."""
    return RoostMessage(
        performative=perf,
        protocol=proto,
        conversation_id=cid,
        sender=AgentAddress(name=sender),
        receivers=[AgentAddress(name=to)],
        envelope=envelope or _envelope(),
        **kwargs,
    )


def test_request_machine_happy_path() -> None:
    """A request agrees then informs successfully."""
    engine = ProtocolEngine()
    request = _msg(P.REQUEST, IP.REQUEST)
    engine.open(request)
    assert engine.accept(request.reply(P.AGREE)).kind == "accepted"
    transition = engine.accept(request.reply(P.INFORM))
    assert transition.state.terminal is TerminalState.INFORMED


@pytest.mark.parametrize(
    ("reply", "terminal"),
    [(P.REFUSE, TerminalState.REFUSED), (P.FAILURE, TerminalState.FAILED)],
)
def test_request_machine_refuse_and_failure(reply: P, terminal: TerminalState) -> None:
    """Request refusal and failure become their specified terminals."""
    engine = ProtocolEngine()
    request = _msg(P.REQUEST, IP.REQUEST)
    engine.open(request)
    assert engine.accept(request.reply(reply)).state.terminal is terminal


def test_query_skips_agree() -> None:
    """Queries resolve directly by inform without an agreement."""
    engine = ProtocolEngine()
    query = _msg(P.QUERY, IP.QUERY)
    engine.open(query)
    assert engine.accept(query.reply(P.INFORM)).state.terminal is TerminalState.INFORMED


def test_out_of_state_not_understood() -> None:
    """An agreement is not valid in the Query protocol."""
    engine = ProtocolEngine()
    query = _msg(P.QUERY, IP.QUERY)
    engine.open(query)
    transition = engine.accept(_msg(P.AGREE, IP.QUERY, sender="b", to="a"))
    assert transition.kind == "not_understood"
    assert transition.emit[0].performative is P.NOT_UNDERSTOOD


def test_closed_conversation_rejects() -> None:
    """Messages received after a terminal transition get not-understood."""
    engine = ProtocolEngine()
    request = _msg(P.REQUEST, IP.REQUEST)
    engine.open(request)
    engine.accept(request.reply(P.REFUSE))
    transition = engine.accept(request.reply(P.INFORM))
    assert transition.kind == "not_understood"
    assert transition.emit[0].performative is P.NOT_UNDERSTOOD


def test_hop_limit_closes_with_failure() -> None:
    """A message over the hop limit closes and targets the requester."""
    engine = ProtocolEngine(default_hop_limit=1)
    request = _msg(P.REQUEST, IP.REQUEST)
    engine.open(request)
    transition = engine.accept(request.reply(P.AGREE), hops=2)
    assert transition.kind == "closed"
    assert transition.emit[0].failure is not None
    assert transition.emit[0].failure.code is FailureCode.HOP_LIMIT
    assert transition.emit[0].receivers == [request.sender]


def test_token_budget_closes_with_failure() -> None:
    """Token consumption beyond the envelope budget emits TOKEN_BUDGET."""
    engine = ProtocolEngine()
    request = _msg(P.REQUEST, IP.REQUEST, envelope=_envelope(token_budget=10))
    engine.open(request)
    transition = engine.charge(request.conversation_id, 11)
    assert transition is not None
    assert transition.emit[0].failure is not None
    assert transition.emit[0].failure.code is FailureCode.TOKEN_BUDGET
    assert transition.emit[0].receivers == [request.sender]


def test_timeout_expire() -> None:
    """Deadlines derive from budget_ms and close with TIMEOUT."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    engine = ProtocolEngine(clock=lambda: now)
    request = _msg(P.REQUEST, IP.REQUEST, envelope=_envelope(budget_ms=100))
    engine.open(request)
    closed = engine.expire(now=now + timedelta(milliseconds=101))
    assert closed[0].emit[0].failure is not None
    assert closed[0].emit[0].failure.code is FailureCode.TIMEOUT
    assert closed[0].emit[0].receivers == [request.sender]


def test_contract_net_award_rule() -> None:
    """Contract Net ranks collected proposal content through the default scorer."""
    engine = ProtocolEngine()
    cfp = _msg(P.CFP, IP.CONTRACT_NET)
    engine.open(cfp)
    engine.accept(_msg(P.PROPOSE, IP.CONTRACT_NET, sender="slow", content={"cost": 4, "time_ms": 8, "confidence": 0.5}))
    engine.accept(_msg(P.PROPOSE, IP.CONTRACT_NET, sender="fast", content={"cost": 1, "time_ms": 1, "confidence": 0.9}))
    award = engine.award(cfp.conversation_id)
    assert award.winner is not None
    assert award.winner.agent_name == "fast"
    assert award.decided_by == "rule"


def test_contract_net_tie_wakes_llm() -> None:
    """Equivalent bids leave the choice to the requester LLM."""
    engine = ProtocolEngine()
    cfp = _msg(P.CFP, IP.CONTRACT_NET)
    engine.open(cfp)
    for sender in ("b", "c"):
        engine.accept(
            _msg(P.PROPOSE, IP.CONTRACT_NET, sender=sender, content={"cost": 1, "time_ms": 1, "confidence": 0.5})
        )
    assert engine.award(cfp.conversation_id).decided_by == "llm"


def test_contract_net_no_bids() -> None:
    """A bid-window expiry without proposals becomes NO_BIDS."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    engine = ProtocolEngine(clock=lambda: now)
    cfp = _msg(P.CFP, IP.CONTRACT_NET)
    engine.open(cfp, budget=ConversationBudget(bid_window_ms=10))
    closed = engine.expire(now=now + timedelta(milliseconds=11))
    assert closed[0].state.terminal is TerminalState.NO_BIDS
    assert engine.award(cfp.conversation_id).winner is None


def test_subscribe_cancel_expire() -> None:
    """Subscriptions remain active for informs and support cancel or expiry."""
    engine = ProtocolEngine()
    subscribe = _msg(P.SUBSCRIBE, IP.SUBSCRIBE)
    engine.open(subscribe)
    notification = _msg(P.INFORM, IP.SUBSCRIBE, sender="b", to="a")
    assert engine.accept(notification).state.state == "active"
    cancelled = engine.close(subscribe.conversation_id, TerminalState.CANCELLED)
    assert cancelled.state.terminal is TerminalState.CANCELLED
    assert cancelled.emit[0].failure is not None
    assert cancelled.emit[0].failure.code is FailureCode.CANCELLED

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    expiry_engine = ProtocolEngine(clock=lambda: now)
    expiring = _msg(P.SUBSCRIBE, IP.SUBSCRIBE)
    expiry_engine.open(expiring, budget=ConversationBudget(deadline=now + timedelta(milliseconds=10)))
    assert expiry_engine.expire(now=now + timedelta(milliseconds=11))[0].state.terminal is TerminalState.TIMED_OUT


def test_not_understood_is_never_answered() -> None:
    """A not-understood arriving for an unknown conversation emits nothing (no ping-pong)."""
    engine = ProtocolEngine()
    stray = engine.accept(_msg(P.AGREE, IP.REQUEST, cid="ghost"))
    assert stray.kind == "not_understood" and len(stray.emit) == 1
    reply = engine.accept(stray.emit[0])
    assert reply.kind == "not_understood" and reply.emit == []
