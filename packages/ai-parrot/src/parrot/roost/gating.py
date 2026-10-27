"""LLM-free gating: decide who wakes from performative, address and protocol state (FEAT-747 M5)."""

from __future__ import annotations

import fnmatch
import logging
from enum import Enum
from typing import Any, Awaitable, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .directory import RoostAgentConfig
from .grant import GrantPolicy
from .messages import RoostMessage
from .performatives import InteractionProtocol, Performative
from .protocols import ProtocolEngine, Transition


class DispatchDecision(str, Enum):
    """Actions an endpoint may take after deterministic gating."""

    IGNORE = "ignore"
    NOT_UNDERSTOOD = "not_understood"
    RUN_TOOL = "run_tool"
    STORE = "store"
    WAKE_LLM = "wake_llm"
    BID_FROM_CONTRACT = "bid_from_contract"
    REPLAN = "replan"
    CLOSED = "closed"


class Handler(Protocol):
    """Asynchronous content handler retained by the endpoint after dispatch."""

    def __call__(self, msg: RoostMessage) -> Awaitable[Optional[Any]]:
        """Handle one message when the endpoint executes the dispatch."""


class HandlerRegistry:
    """Handlers keyed by ``content_type`` (dotted class name or media type; ``"*"`` wildcard)."""

    def __init__(self) -> None:
        self._handlers: dict[str, tuple[Handler, bool]] = {}

    def register(self, content_type: str, handler: Handler, *, needs_decision: bool = False) -> None:
        """Register a handler and whether its messages need an LLM decision."""
        self._handlers[content_type] = (handler, needs_decision)

    def resolve(self, content_type: Optional[str]) -> Optional[tuple[Handler, bool]]:
        """Return an exact handler first, then the wildcard handler if registered."""
        return self._handlers.get(content_type or "") or self._handlers.get("*")


class Dispatch(BaseModel):
    """The deterministic result that an endpoint must execute."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    decision: DispatchDecision
    transition: Optional[Transition] = None
    emit: list[RoostMessage] = Field(default_factory=list)
    handler: Any = None


class GatingDispatcher:
    """Apply address, state and decision gates without invoking an LLM."""

    def __init__(
        self,
        *,
        self_name: str,
        config: Optional[RoostAgentConfig],
        engine: ProtocolEngine,
        handlers: HandlerRegistry,
        grant: GrantPolicy,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.self_name = self_name
        self.config = config
        self.engine = engine
        self.handlers = handlers
        self.grant = grant
        self._wakes = 0

    def addressed(self, msg: RoostMessage) -> bool:
        """Return whether the message names this endpoint or matches one advertised capability."""
        if msg.is_addressed_to(self.self_name):
            return True
        if self.config is None or msg.capability_filter is None:
            return False
        return any(fnmatch.fnmatchcase(capability, msg.capability_filter) for capability in self.config.capabilities)

    def dispatch(self, msg: RoostMessage, *, hops: int = 0) -> Dispatch:
        """Apply address, protocol-state, and decision gates without executing their result."""
        directly_addressed = msg.is_addressed_to(self.self_name)
        if not directly_addressed and not self.addressed(msg):
            return Dispatch(decision=DispatchDecision.IGNORE)

        transition: Optional[Transition] = None
        openers = {
            Performative.REQUEST,
            Performative.QUERY,
            Performative.CFP,
            Performative.SUBSCRIBE,
            Performative.INFORM,
        }
        if msg.performative in openers and self.engine.state(msg.conversation_id) is None:
            self.engine.open(msg)
            exceeded = self.engine.check_hops(msg)
            if exceeded is not None:
                return Dispatch(decision=DispatchDecision.CLOSED, transition=exceeded, emit=exceeded.emit)
        else:
            transition = self.engine.accept(msg, hops=hops)
            if transition.kind == "not_understood":
                return Dispatch(
                    decision=DispatchDecision.NOT_UNDERSTOOD,
                    transition=transition,
                    emit=transition.emit,
                )
            if transition.kind == "closed":
                return Dispatch(decision=DispatchDecision.CLOSED, transition=transition, emit=transition.emit)

        handler: Optional[Handler] = None
        if msg.performative in (Performative.REQUEST, Performative.QUERY):
            decision = (
                DispatchDecision.RUN_TOOL
                if self.config is not None and self.config.backing == "deterministic"
                else DispatchDecision.WAKE_LLM
            )
        elif msg.performative is Performative.INFORM:
            if transition is not None and msg.protocol in (InteractionProtocol.REQUEST, InteractionProtocol.QUERY):
                # Terminal reply to our own request/query: the awaiting caller gets it by identity, no LLM wake.
                decision = DispatchDecision.STORE
            elif directly_addressed:
                decision = DispatchDecision.WAKE_LLM
            else:
                resolved = self.handlers.resolve(msg.content_type)
                handler = resolved[0] if resolved is not None else None
                decision = DispatchDecision.WAKE_LLM if resolved is not None and resolved[1] else DispatchDecision.STORE
        elif msg.performative is Performative.CFP:
            decision = (
                DispatchDecision.BID_FROM_CONTRACT
                if self.config is not None and self.config.bid is not None
                else DispatchDecision.WAKE_LLM
            )
        elif msg.performative is Performative.FAILURE:
            decision = DispatchDecision.REPLAN
        else:
            decision = DispatchDecision.STORE

        if decision in (DispatchDecision.WAKE_LLM, DispatchDecision.REPLAN):
            self._wakes += 1
        return Dispatch(decision=decision, transition=transition, handler=handler)

    @property
    def wakes(self) -> int:
        """Return the number of LLM or replanning wake decisions emitted."""
        return self._wakes
