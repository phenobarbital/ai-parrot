"""Lifecycle Events System — typed, frozen, observability-first events.

FEAT-176. Public API curation (TASK-1197).

Usage::

    from parrot.core.events.lifecycle import (
        EventRegistry, EventEmitterMixin, TraceContext,
        BeforeInvokeEvent, AfterInvokeEvent,
        scope,
    )
"""

from parrot.core.events.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.base import LifecycleEvent
from parrot.core.events.lifecycle.meta import SubscriberErrorEvent
from parrot.core.events.lifecycle.registry import EventRegistry, AsyncSubscriber
from parrot.core.events.lifecycle.global_registry import get_global_registry, scope
from parrot.core.events.lifecycle.provider import EventProvider
from parrot.core.events.lifecycle.mixin import EventEmitterMixin

# Concrete events
from parrot.core.events.lifecycle.events import (
    AgentInitializedEvent,
    AgentConfiguredEvent,
    ToolManagerReadyEvent,
    AgentStatusChangedEvent,
    BeforeInvokeEvent,
    AfterInvokeEvent,
    InvokeFailedEvent,
    BeforeClientCallEvent,
    AfterClientCallEvent,
    ClientCallFailedEvent,
    ClientStreamChunkEvent,
    BeforeToolCallEvent,
    AfterToolCallEvent,
    ToolCallFailedEvent,
    MessageAddedEvent,
)

# Built-in subscribers
from parrot.core.events.lifecycle.subscribers.logging import LoggingSubscriber
from parrot.core.events.lifecycle.subscribers.opentelemetry import OpenTelemetrySubscriber
from parrot.core.events.lifecycle.subscribers.webhook import WebhookSubscriber


__all__ = [
    # Trace
    "TraceContext",
    # Base + meta
    "LifecycleEvent",
    "SubscriberErrorEvent",
    # Concrete events — agent
    "AgentInitializedEvent",
    "AgentConfiguredEvent",
    "ToolManagerReadyEvent",
    "AgentStatusChangedEvent",
    # Concrete events — invocation
    "BeforeInvokeEvent",
    "AfterInvokeEvent",
    "InvokeFailedEvent",
    # Concrete events — client
    "BeforeClientCallEvent",
    "AfterClientCallEvent",
    "ClientCallFailedEvent",
    "ClientStreamChunkEvent",
    # Concrete events — tool
    "BeforeToolCallEvent",
    "AfterToolCallEvent",
    "ToolCallFailedEvent",
    # Concrete events — message
    "MessageAddedEvent",
    # Registry + dispatch
    "EventRegistry",
    "AsyncSubscriber",
    "get_global_registry",
    "scope",
    # Provider + mixin
    "EventProvider",
    "EventEmitterMixin",
    # Built-in subscribers
    "LoggingSubscriber",
    "OpenTelemetrySubscriber",
    "WebhookSubscriber",
]
