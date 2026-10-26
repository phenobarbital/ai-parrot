"""Roost — local inter-agent sub-protocol over the Squawk envelope (FEAT-747).

Exports are resolved lazily (PEP 562) so ``import parrot.roost`` stays cheap and no submodule is imported
until a name is used. Every later Roost task adds its module WITHOUT editing this file: the map below
already names it.
"""
from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    "Performative": "performatives", "InteractionProtocol": "performatives", "FailureCode": "performatives",
    "CarrierKind": "performatives", "ReplyObligation": "performatives", "OBLIGATIONS": "performatives",
    "ORIGIN_TOOL_MAP": "performatives", "obligation_for": "performatives",
    "EnvelopeLike": "messages", "LocalEnvelope": "messages", "AgentAddress": "messages",
    "FailureInfo": "messages", "RoostMessage": "messages",
    "Bid": "scoring", "Award": "scoring", "BidScorer": "scoring", "FixedWeightScorer": "scoring",
    "ProtocolEngine": "protocols", "ConversationBudget": "protocols", "ConversationState": "protocols",
    "TerminalState": "protocols", "Transition": "protocols", "ConversationExistsError": "protocols",
    "Locality": "directory", "InterAgentGrant": "directory", "RoostAgentConfig": "directory",
    "CapabilityMatch": "directory", "GrantPolicy": "grant", "GrantDenied": "grant",
    "GatingDispatcher": "gating", "HandlerRegistry": "gating", "DispatchDecision": "gating", "Dispatch": "gating",
    "Blackboard": "blackboard", "InMemoryBlackboard": "blackboard", "BlackboardKey": "blackboard",
    "BlackboardEntry": "blackboard", "KeyACL": "blackboard", "WriterPolicy": "blackboard",
    "StaleWriteError": "blackboard", "WriterDeniedError": "blackboard", "ReadDeniedError": "blackboard",
    "Carrier": "carriers.base", "CarrierError": "carriers.base", "Undeliverable": "carriers.base",
    "CarrierClosed": "carriers.base", "InProcessCarrier": "carriers.inprocess",
    "SharedMemoryCarrier": "carriers.shm", "EventBusCarrier": "carriers.bus",
    "EnvelopeCodec": "codec", "JsonEnvelopeCodec": "codec", "UnencodableContent": "codec",
    "RoostAuditLedger": "audit", "RoostAuditEntry": "audit",
    "RoostEndpoint": "endpoint", "RoostFailure": "endpoint", "RoostToolkit": "toolkit",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    """Resolve *name* from its submodule on first use (PEP 562)."""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Return module globals and the complete lazy public interface."""
    return sorted(set(globals()) | set(_EXPORTS))
