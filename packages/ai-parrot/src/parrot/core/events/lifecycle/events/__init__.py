"""Re-exports for all concrete lifecycle event classes.

FEAT-176 — Lifecycle Events System.

Import any event class from this package for convenience:

    from parrot.core.events.lifecycle.events import BeforeInvokeEvent

SubscriberErrorEvent lives in meta.py (not here) because it is a
meta-level event emitted by the registry, not by domain code.
"""
from parrot.core.events.lifecycle.events.agent import (
    AgentInitializedEvent,
    AgentConfiguredEvent,
    ToolManagerReadyEvent,
    AgentStatusChangedEvent,
)
from parrot.core.events.lifecycle.events.invoke import (
    BeforeInvokeEvent,
    AfterInvokeEvent,
    InvokeFailedEvent,
)
from parrot.core.events.lifecycle.events.client import (
    BeforeClientCallEvent,
    AfterClientCallEvent,
    ClientCallFailedEvent,
    ClientStreamChunkEvent,
)
from parrot.core.events.lifecycle.events.tool import (
    BeforeToolCallEvent,
    AfterToolCallEvent,
    ToolCallFailedEvent,
)
from parrot.core.events.lifecycle.events.message import MessageAddedEvent

__all__ = [
    # Agent domain
    "AgentInitializedEvent",
    "AgentConfiguredEvent",
    "ToolManagerReadyEvent",
    "AgentStatusChangedEvent",
    # Invocation domain
    "BeforeInvokeEvent",
    "AfterInvokeEvent",
    "InvokeFailedEvent",
    # Client domain
    "BeforeClientCallEvent",
    "AfterClientCallEvent",
    "ClientCallFailedEvent",
    "ClientStreamChunkEvent",
    # Tool domain
    "BeforeToolCallEvent",
    "AfterToolCallEvent",
    "ToolCallFailedEvent",
    # Message domain
    "MessageAddedEvent",
]
