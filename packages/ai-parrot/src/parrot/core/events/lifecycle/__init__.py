"""Lifecycle Events System — typed, frozen, observability-first events.

FEAT-176. Public API curation (TASK-1197).

FEAT-317: the lifecycle machinery (``TraceContext``, ``LifecycleEvent``,
``EventRegistry``, ``EventEmitterMixin``, etc.) was extracted to
``navigator_eventbus.lifecycle`` (FEAT-313). This module re-exports that
machinery alongside ai-parrot's own typed events (which stay local) and
built-in subscribers, preserving the public surface consumers rely on::

    from parrot.core.events.lifecycle import (
        EventRegistry, EventEmitterMixin, TraceContext,
        BeforeInvokeEvent, AfterInvokeEvent,
        scope,
    )
"""

from navigator_eventbus.lifecycle.trace import TraceContext
from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.meta import SubscriberErrorEvent
from navigator_eventbus.lifecycle.registry import EventRegistry, AsyncSubscriber
from navigator_eventbus.lifecycle.global_registry import get_global_registry, scope
from navigator_eventbus.lifecycle.provider import EventProvider
from navigator_eventbus.lifecycle.mixin import EventEmitterMixin

# Concrete events — STAY local (ai-parrot's own taxonomy)
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
    FlowStartedEvent,
    FlowCompletedEvent,
    NodeStartedEvent,
    NodeCompletedEvent,
    NodeFailedEvent,
    NodeSkippedEvent,
)

# Built-in subscribers — Logging/Webhook from the package; OpenTelemetry
# depends on ai-parrot's typed events, so it stays local.
from navigator_eventbus.lifecycle.subscribers.logging import LoggingSubscriber
from parrot.core.events.lifecycle.subscribers.opentelemetry import OpenTelemetrySubscriber
from navigator_eventbus.lifecycle.subscribers.webhook import WebhookSubscriber


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
    "FlowStartedEvent",
    "FlowCompletedEvent",
    "NodeStartedEvent",
    "NodeCompletedEvent",
    "NodeFailedEvent",
    "NodeSkippedEvent",
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
