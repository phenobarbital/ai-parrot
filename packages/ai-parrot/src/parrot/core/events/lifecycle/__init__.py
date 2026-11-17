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
from navigator_eventbus.lifecycle.mixin import EventEmitterMixin, set_bootstrap_hook
from parrot.core.events.lifecycle.turn_scope import TURN_SCOPE, turn_scope, in_turn_scope  # FEAT-573 M3

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
    # Turn correlation (FEAT-573)
    "TURN_SCOPE",
    "turn_scope",
    "in_turn_scope",
    # Provider + mixin
    "EventProvider",
    "EventEmitterMixin",
    # Built-in subscribers
    "LoggingSubscriber",
    "OpenTelemetrySubscriber",
    "WebhookSubscriber",
]


def _observability_bootstrap_hook() -> None:
    """Run ai-parrot's env-driven observability auto-boot.

    Installed process-wide via :func:`set_bootstrap_hook` so that
    ``EventEmitterMixin._init_events()`` boots observability on the first
    bot/client/tool construction, as it did before FEAT-313 extracted the
    mixin to ``navigator_eventbus`` (the deleted ``mixin.py`` hard-imported
    the bootstrap at that point).

    The import is deferred to call time on purpose: ``parrot.observability``
    imports subscribers that import this very module, so a module-level
    import would be circular. ``ensure_observability_bootstrapped`` is itself
    idempotent, which the hook contract requires — the hook runs on *every*
    ``_init_events()`` call, not just the first.
    """
    from parrot.observability.bootstrap import ensure_observability_bootstrapped  # noqa: PLC0415

    ensure_observability_bootstrapped()


# FEAT-725: re-arm the auto-boot that b1388892f (TASK-1828) silently dropped
# when it deleted ai-parrot's own EventEmitterMixin.
set_bootstrap_hook(_observability_bootstrap_hook)
