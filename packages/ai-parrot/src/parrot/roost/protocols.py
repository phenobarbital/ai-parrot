"""Roost interaction protocols — pure per-conversation state machines (FEAT-747 M2)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, ClassVar, Literal, Optional

from pydantic import BaseModel, Field

from .messages import AgentAddress, FailureInfo, RoostMessage
from .performatives import FailureCode, InteractionProtocol, Performative
from .scoring import Award, Bid, BidScorer, rank_bids

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class TerminalState(str, Enum):
    """Terminal outcomes for a Roost conversation."""

    DONE = "done"
    INFORMED = "informed"
    REFUSED = "refused"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    AWARDED = "awarded"
    NO_BIDS = "no_bids"
    EXPIRED = "expired"


class ConversationExistsError(ValueError):
    """Raised when ``ProtocolEngine.open`` receives an already-open id."""


class ConversationBudget(BaseModel):
    """Limits applied to one conversation."""

    hop_limit: int = 8
    hops: int = 0
    token_budget: Optional[int] = None
    tokens_used: int = 0
    deadline: Optional[datetime] = None
    bid_window_ms: Optional[int] = None


class ConversationState(BaseModel):
    """Mutable deterministic state held for one conversation id."""

    conversation_id: str
    protocol: InteractionProtocol
    initiator: AgentAddress
    state: str
    terminal: Optional[TerminalState] = None
    budget: ConversationBudget = Field(default_factory=ConversationBudget)
    last_message_id: Optional[str] = None
    proposals: list[RoostMessage] = Field(default_factory=list)
    opened_at: datetime = Field(default_factory=_utcnow)


class Transition(BaseModel):
    """One deterministic protocol transition and any required output."""

    kind: Literal["accepted", "not_understood", "closed"]
    state: ConversationState
    obligations: tuple[Performative, ...] = ()
    emit: list[RoostMessage] = Field(default_factory=list)


class ProtocolMachine(ABC):
    """State machine for one protocol. Pure: no I/O, no clock reads."""

    protocol: ClassVar[InteractionProtocol]

    @abstractmethod
    def initial_state(self, opener: RoostMessage) -> str:
        """Return the initial state label for *opener*."""

    @abstractmethod
    def step(self, state: ConversationState, msg: RoostMessage, *, now: datetime) -> Transition:
        """Apply *msg* to *state* without performing I/O."""


class InformMachine(ProtocolMachine):
    """Inform is complete as soon as its opener is recorded."""

    protocol = InteractionProtocol.INFORM

    def initial_state(self, opener: RoostMessage) -> str:
        """Return the sole Inform state."""
        return "informed"

    def step(self, state: ConversationState, msg: RoostMessage, *, now: datetime) -> Transition:
        """Reject all messages after the opener."""
        return _not_understood(state, msg)


class RequestMachine(ProtocolMachine):
    """Request transitions through agreement to an outcome."""

    protocol = InteractionProtocol.REQUEST

    def initial_state(self, opener: RoostMessage) -> str:
        """Return the initial request state."""
        return "awaiting_agree"

    def step(self, state: ConversationState, msg: RoostMessage, *, now: datetime) -> Transition:
        """Apply one Request reply."""
        if state.state == "awaiting_agree":
            if msg.performative is Performative.AGREE:
                state.state = "awaiting_result"
                return _accepted(state, msg, (Performative.INFORM, Performative.FAILURE))
            if msg.performative is Performative.REFUSE:
                state.terminal = TerminalState.REFUSED
                return _accepted(state, msg)
            if msg.performative is Performative.INFORM:
                state.terminal = TerminalState.INFORMED
                return _accepted(state, msg)
            if msg.performative is Performative.FAILURE:
                state.terminal = TerminalState.FAILED
                return _accepted(state, msg)
        elif state.state == "awaiting_result":
            if msg.performative is Performative.INFORM:
                state.terminal = TerminalState.INFORMED
                return _accepted(state, msg)
            if msg.performative is Performative.FAILURE:
                state.terminal = TerminalState.FAILED
                return _accepted(state, msg)
        return _not_understood(state, msg)


class QueryMachine(ProtocolMachine):
    """Query waits directly for an answer or failure."""

    protocol = InteractionProtocol.QUERY

    def initial_state(self, opener: RoostMessage) -> str:
        """Return the initial query state."""
        return "awaiting_result"

    def step(self, state: ConversationState, msg: RoostMessage, *, now: datetime) -> Transition:
        """Apply one Query reply."""
        if state.state == "awaiting_result" and msg.performative is Performative.INFORM:
            state.terminal = TerminalState.INFORMED
            return _accepted(state, msg)
        if state.state == "awaiting_result" and msg.performative is Performative.FAILURE:
            state.terminal = TerminalState.FAILED
            return _accepted(state, msg)
        return _not_understood(state, msg)


class ContractNetMachine(ProtocolMachine):
    """Contract Net collects proposals until its bid window closes."""

    protocol = InteractionProtocol.CONTRACT_NET

    def initial_state(self, opener: RoostMessage) -> str:
        """Return the proposal-collection state."""
        return "collecting_bids"

    def step(self, state: ConversationState, msg: RoostMessage, *, now: datetime) -> Transition:
        """Collect proposals and refusals while the bid window is active."""
        if state.state == "collecting_bids" and msg.performative is Performative.PROPOSE:
            state.proposals.append(msg)
            return _accepted(state, msg, (Performative.ACCEPT, Performative.REJECT))
        if state.state == "collecting_bids" and msg.performative is Performative.REFUSE:
            return _accepted(state, msg)
        return _not_understood(state, msg)


class SubscribeMachine(ProtocolMachine):
    """Subscribe remains active while it receives notification informs."""

    protocol = InteractionProtocol.SUBSCRIBE

    def initial_state(self, opener: RoostMessage) -> str:
        """Return the active subscription state."""
        return "active"

    def step(self, state: ConversationState, msg: RoostMessage, *, now: datetime) -> Transition:
        """Accept repeated informs while the subscription is active."""
        if state.state == "active" and msg.performative is Performative.INFORM:
            return _accepted(state, msg)
        return _not_understood(state, msg)


MACHINES: dict[InteractionProtocol, ProtocolMachine] = {
    InteractionProtocol.INFORM: InformMachine(),
    InteractionProtocol.REQUEST: RequestMachine(),
    InteractionProtocol.QUERY: QueryMachine(),
    InteractionProtocol.CONTRACT_NET: ContractNetMachine(),
    InteractionProtocol.SUBSCRIBE: SubscribeMachine(),
}


def _accepted(state: ConversationState, msg: RoostMessage, obligations: tuple[Performative, ...] = ()) -> Transition:
    """Record *msg* and return a successful transition."""
    state.last_message_id = msg.message_id
    return Transition(kind="accepted", state=state, obligations=obligations)


def _not_understood(state: ConversationState, msg: RoostMessage) -> Transition:
    """Return the standard out-of-state reply transition."""
    if msg.performative is Performative.NOT_UNDERSTOOD:
        # A not-understood is never answered: replying to it would ping-pong between two endpoints forever.
        return Transition(kind="not_understood", state=state, emit=[])
    return Transition(kind="not_understood", state=state, emit=[msg.reply(Performative.NOT_UNDERSTOOD)])


class ProtocolEngine:
    """Owns ConversationState per conversation_id and applies the machines deterministically."""

    def __init__(
        self,
        *,
        default_hop_limit: int = 8,
        scorer: Optional[BidScorer] = None,
        tie_epsilon: float = 1e-6,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self._states: dict[str, ConversationState] = {}
        self._default_hop_limit = default_hop_limit
        self._scorer = scorer
        self._tie_epsilon = tie_epsilon
        self._clock = clock

    def open(self, opener: RoostMessage, *, budget: Optional[ConversationBudget] = None) -> ConversationState:
        """Create state for ``opener.conversation_id``; budget defaults from ``opener.envelope``.

        Raises:
            ConversationExistsError: If the id is already open.
        """
        if opener.conversation_id in self._states:
            raise ConversationExistsError(opener.conversation_id)
        now = self._clock()
        if budget is None:
            budget_ms = getattr(opener.envelope, "budget_ms", None)
            budget = ConversationBudget(
                hop_limit=self._default_hop_limit,
                token_budget=getattr(opener.envelope, "token_budget", None),
                deadline=now + timedelta(milliseconds=budget_ms) if budget_ms is not None else None,
            )
        machine = MACHINES[opener.protocol]
        terminal = TerminalState.DONE if opener.protocol is InteractionProtocol.INFORM else None
        state = ConversationState(
            conversation_id=opener.conversation_id,
            protocol=opener.protocol,
            initiator=opener.sender,
            state=machine.initial_state(opener),
            terminal=terminal,
            budget=budget,
            last_message_id=opener.message_id,
            opened_at=now,
        )
        self._states[state.conversation_id] = state
        return state

    def accept(self, msg: RoostMessage, *, hops: int = 0) -> Transition:
        """Apply *msg*; never raises on protocol errors."""
        state = self._states.get(msg.conversation_id)
        if state is None or state.protocol is not msg.protocol or state.terminal is not None:
            return self._not_understood_for_unknown(msg, state)
        state.budget.hops += hops
        if state.budget.hops > state.budget.hop_limit:
            return self._close_with_failure(state, FailureCode.HOP_LIMIT, "conversation hop limit exceeded", msg)
        transition = MACHINES[state.protocol].step(state, msg, now=self._clock())
        if transition.kind == "not_understood":
            self.logger.info("Roost protocol did not understand message %s", msg.message_id)
        return transition

    def charge(self, conversation_id: str, tokens: int) -> Optional[Transition]:
        """Consume LLM tokens and close if the configured budget is exhausted."""
        state = self._states.get(conversation_id)
        if state is None or state.terminal is not None:
            return None
        state.budget.tokens_used += tokens
        if state.budget.token_budget is not None and state.budget.tokens_used > state.budget.token_budget:
            return self._close_with_failure(state, FailureCode.TOKEN_BUDGET, "conversation token budget exceeded")
        return None

    def expire(self, *, now: Optional[datetime] = None) -> list[Transition]:
        """Close conversations past their deadline or Contract Net bid window."""
        current_time = now or self._clock()
        closed: list[Transition] = []
        for state in self._states.values():
            if state.terminal is not None:
                continue
            if state.budget.deadline is not None and current_time > state.budget.deadline:
                closed.append(self._close_with_failure(state, FailureCode.TIMEOUT, "conversation deadline exceeded"))
                continue
            if (
                state.protocol is InteractionProtocol.CONTRACT_NET
                and state.budget.bid_window_ms is not None
                and current_time > state.opened_at + timedelta(milliseconds=state.budget.bid_window_ms)
            ):
                award = self.award(state.conversation_id)
                state.terminal = TerminalState.AWARDED if award.winner is not None else TerminalState.NO_BIDS
                state.state = "awarded" if award.winner is not None else "no_bids"
                closed.append(Transition(kind="closed", state=state))
        return closed

    def award(self, conversation_id: str) -> Award:
        """Score collected proposals with ``rank_bids``."""
        state = self._states.get(conversation_id)
        if state is None or state.protocol is not InteractionProtocol.CONTRACT_NET:
            return Award()
        bids = [
            Bid(
                agent_name=proposal.sender.name,
                cost=proposal.content["cost"] if isinstance(proposal.content, dict) else proposal.content.cost,
                time_ms=proposal.content["time_ms"] if isinstance(proposal.content, dict) else proposal.content.time_ms,
                confidence=(
                    proposal.content["confidence"]
                    if isinstance(proposal.content, dict)
                    else proposal.content.confidence
                ),
                message_id=proposal.message_id,
            )
            for proposal in state.proposals
        ]
        return rank_bids(bids, self._scorer, tie_epsilon=self._tie_epsilon)

    def state(self, conversation_id: str) -> Optional[ConversationState]:
        """Return state for *conversation_id*, if present."""
        return self._states.get(conversation_id)

    def close(self, conversation_id: str, terminal: TerminalState, *, reason: str = "") -> Transition:
        """Force a terminal state, such as cancellation."""
        state = self._states[conversation_id]
        state.terminal = terminal
        state.state = terminal.value
        emit: list[RoostMessage] = []
        if terminal is TerminalState.CANCELLED:
            emit.append(
                RoostMessage(
                    performative=Performative.REJECT,
                    protocol=state.protocol,
                    conversation_id=state.conversation_id,
                    in_reply_to=state.last_message_id,
                    sender=AgentAddress(name="protocol-engine"),
                    receivers=[state.initiator],
                    failure=FailureInfo(code=FailureCode.CANCELLED, detail=reason),
                )
            )
        return Transition(kind="closed", state=state, emit=emit)

    def _not_understood_for_unknown(self, msg: RoostMessage, state: Optional[ConversationState]) -> Transition:
        """Build a not-understood transition for unknown or closed conversations."""
        if state is None:
            state = ConversationState(
                conversation_id=msg.conversation_id,
                protocol=msg.protocol,
                initiator=msg.receivers[0] if msg.receivers else msg.sender,
                state="unknown",
            )
        return _not_understood(state, msg)

    def _close_with_failure(
        self,
        state: ConversationState,
        code: FailureCode,
        detail: str,
        source: Optional[RoostMessage] = None,
    ) -> Transition:
        """Close *state* and emit an engine-originated typed failure to its initiator."""
        state.terminal = TerminalState.TIMED_OUT if code is FailureCode.TIMEOUT else TerminalState.FAILED
        state.state = state.terminal.value
        sender = (
            source.receivers[0] if source is not None and source.receivers else AgentAddress(name="protocol-engine")
        )
        failure = RoostMessage(
            performative=Performative.FAILURE,
            protocol=state.protocol,
            conversation_id=state.conversation_id,
            in_reply_to=source.message_id if source is not None else state.last_message_id,
            sender=sender,
            receivers=[state.initiator],
            failure=FailureInfo(code=code, detail=detail),
        )
        return Transition(kind="closed", state=state, emit=[failure])
