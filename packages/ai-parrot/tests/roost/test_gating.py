"""Unit tests for the deterministic Roost gating dispatcher."""

from typing import Any, Optional

from parrot.roost.directory import RoostAgentConfig
from parrot.roost.gating import DispatchDecision as D
from parrot.roost.gating import GatingDispatcher, HandlerRegistry
from parrot.roost.grant import GrantPolicy
from parrot.roost.messages import AgentAddress, RoostMessage
from parrot.roost.performatives import InteractionProtocol as IP
from parrot.roost.performatives import Performative as P
from parrot.roost.protocols import ProtocolEngine


def _disp(**config: Any) -> GatingDispatcher:
    """Build a dispatcher advertising the salary capability."""
    return GatingDispatcher(
        self_name="hr",
        config=RoostAgentConfig(capabilities=["hr.people.salary"], **config),
        engine=ProtocolEngine(),
        handlers=HandlerRegistry(),
        grant=GrantPolicy(),
    )


def _message(
    performative: P,
    protocol: IP,
    receivers: tuple[str, ...] = ("hr",),
    capability_filter: Optional[str] = None,
    conversation_id: str = "conversation",
    content_type: Optional[str] = None,
) -> RoostMessage:
    """Build one valid message with deterministic addressing details."""
    return RoostMessage(
        performative=performative,
        protocol=protocol,
        conversation_id=conversation_id,
        sender=AgentAddress(name="caller"),
        receivers=[AgentAddress(name=name) for name in receivers],
        capability_filter=capability_filter,
        content_type=content_type,
    )


def test_addressed_deterministic_request_runs_tool() -> None:
    """A directly addressed deterministic request does not wake the LLM."""
    dispatcher = _disp(backing="deterministic")

    assert dispatcher.dispatch(_message(P.REQUEST, IP.REQUEST)).decision is D.RUN_TOOL
    assert dispatcher.wakes == 0


def test_inform_addressed_wakes_broadcast_stores() -> None:
    """Direct informs wake, while capability broadcasts without a handler only store."""
    dispatcher = _disp()

    assert dispatcher.dispatch(_message(P.INFORM, IP.INFORM, conversation_id="direct")).decision is D.WAKE_LLM
    assert (
        dispatcher.dispatch(_message(P.INFORM, IP.INFORM, (), "hr.*", conversation_id="broadcast")).decision is D.STORE
    )
    assert dispatcher.wakes == 1


def test_broadcast_inform_with_decision_handler_wakes() -> None:
    """A registered decision-needed handler wakes for a matching broadcast inform."""
    dispatcher = _disp()

    async def handler(message: RoostMessage) -> Optional[Any]:
        """Accept a stored message in the endpoint phase."""
        return message.content

    dispatcher.handlers.register("application/salary", handler, needs_decision=True)
    result = dispatcher.dispatch(
        _message(P.INFORM, IP.INFORM, (), "hr.*", conversation_id="handler", content_type="application/salary")
    )

    assert result.decision is D.WAKE_LLM
    assert result.handler is handler
    assert dispatcher.wakes == 1


def test_handler_registry_prefers_exact_content_type_over_wildcard() -> None:
    """Exact handlers take precedence over the registered wildcard handler."""
    registry = HandlerRegistry()

    async def exact_handler(message: RoostMessage) -> Optional[Any]:
        """Handle the exact content type."""
        return message.content

    async def wildcard_handler(message: RoostMessage) -> Optional[Any]:
        """Handle otherwise unmatched content types."""
        return message.content

    registry.register("*", wildcard_handler)
    registry.register("application/salary", exact_handler, needs_decision=True)

    assert registry.resolve("application/salary") == (exact_handler, True)
    assert registry.resolve("application/other") == (wildcard_handler, False)


def test_cfp_with_bid_contract_does_not_wake() -> None:
    """Fixed-price Contract Net capability bids deterministically."""
    dispatcher = _disp(bid={"cost": 1.0})

    assert dispatcher.dispatch(_message(P.CFP, IP.CONTRACT_NET)).decision is D.BID_FROM_CONTRACT
    assert dispatcher.wakes == 0


def test_unaddressed_message_is_ignored_without_engine_state() -> None:
    """Messages for another endpoint do not create protocol state or a wake."""
    dispatcher = _disp()
    message = _message(P.INFORM, IP.INFORM, receivers=("other",), conversation_id="ignored")

    assert dispatcher.dispatch(message).decision is D.IGNORE
    assert dispatcher.engine.state(message.conversation_id) is None
    assert dispatcher.wakes == 0


def test_out_of_state_reply_returns_not_understood_with_emit() -> None:
    """An invalid reply is converted into the engine's emitted not-understood response."""
    dispatcher = _disp()
    opener = _message(P.REQUEST, IP.REQUEST, conversation_id="request")
    invalid_reply = _message(P.PROPOSE, IP.REQUEST, conversation_id="request")

    dispatcher.dispatch(opener)
    result = dispatcher.dispatch(invalid_reply)

    assert result.decision is D.NOT_UNDERSTOOD
    assert result.transition is not None
    assert result.emit == result.transition.emit
    assert result.emit[0].performative is P.NOT_UNDERSTOOD
