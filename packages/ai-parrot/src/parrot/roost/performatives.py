"""Roost speech acts, protocols, failure codes and reply obligations (FEAT-747 M1)."""
from __future__ import annotations

from enum import Enum
from typing import Final, Literal

from pydantic import BaseModel


class Performative(str, Enum):
    """The twelve Roost speech acts (FIPA-ACL subset, spec L2)."""

    INFORM = "inform"
    REQUEST = "request"
    QUERY = "query"
    AGREE = "agree"
    REFUSE = "refuse"
    FAILURE = "failure"
    CFP = "cfp"
    PROPOSE = "propose"
    ACCEPT = "accept"
    REJECT = "reject"
    SUBSCRIBE = "subscribe"
    NOT_UNDERSTOOD = "not_understood"


class InteractionProtocol(str, Enum):
    """Per-conversation state machines enforced by the harness."""

    INFORM = "inform"
    REQUEST = "request"
    QUERY = "query"
    CONTRACT_NET = "contract_net"
    SUBSCRIBE = "subscribe"


class FailureCode(str, Enum):
    """Typed reasons carried by a ``failure`` act."""

    TIMEOUT = "TIMEOUT"
    HOP_LIMIT = "HOP_LIMIT"
    TOKEN_BUDGET = "TOKEN_BUDGET"
    POLICY = "POLICY"
    CAPACITY = "CAPACITY"
    NO_BIDS = "NO_BIDS"
    CANCELLED = "CANCELLED"
    STALE_CONTRACT = "STALE_CONTRACT"
    INTERNAL = "INTERNAL"


class CarrierKind(str, Enum):
    """The four local carriers (spec L9 / G7)."""

    IN_PROCESS = "in_process"
    SAME_HOST = "same_host"
    NETWORK = "network"
    MATRIX = "matrix"


WakeRule = Literal["never", "if_llm_backed", "if_addressed", "if_capability_matches", "requester_to_replan"]


class ReplyObligation(BaseModel):
    """Whether a reply is owed, which acts may answer, and when the receiver's LLM wakes."""

    owed: bool
    allowed_replies: tuple[Performative, ...] = ()
    wakes_receiver: WakeRule = "never"


OBLIGATIONS: Final[dict[Performative, ReplyObligation]] = {
    Performative.INFORM: ReplyObligation(owed=False, wakes_receiver="if_addressed"),
    Performative.REQUEST: ReplyObligation(
        owed=True,
        allowed_replies=(Performative.AGREE, Performative.REFUSE, Performative.INFORM, Performative.FAILURE),
        wakes_receiver="if_llm_backed",
    ),
    Performative.QUERY: ReplyObligation(
        owed=True,
        allowed_replies=(Performative.INFORM, Performative.FAILURE),
        wakes_receiver="if_llm_backed",
    ),
    Performative.AGREE: ReplyObligation(owed=False),
    Performative.REFUSE: ReplyObligation(owed=False),
    Performative.FAILURE: ReplyObligation(owed=False, wakes_receiver="requester_to_replan"),
    Performative.CFP: ReplyObligation(
        owed=True,
        allowed_replies=(Performative.PROPOSE, Performative.REFUSE),
        wakes_receiver="if_capability_matches",
    ),
    Performative.PROPOSE: ReplyObligation(
        owed=True,
        allowed_replies=(Performative.ACCEPT, Performative.REJECT),
    ),
    Performative.ACCEPT: ReplyObligation(
        owed=True,
        allowed_replies=(Performative.AGREE, Performative.REFUSE),
        wakes_receiver="if_llm_backed",
    ),
    Performative.REJECT: ReplyObligation(owed=False),
    Performative.SUBSCRIBE: ReplyObligation(owed=False),
    Performative.NOT_UNDERSTOOD: ReplyObligation(owed=False),
}

#: Origin tool name → act. Mounted capability tools map to REQUEST in the toolkit, not by name.
ORIGIN_TOOL_MAP: Final[dict[str, Performative]] = {
    "report": Performative.INFORM,
    "ask_agent": Performative.QUERY,
    "call_for_proposals": Performative.CFP,
    "watch": Performative.SUBSCRIBE,
}


def obligation_for(performative: Performative) -> ReplyObligation:
    """Return the reply obligation and wake rule for *performative* (never raises)."""
    return OBLIGATIONS[performative]
