"""Meta-events for error isolation (model B).

FEAT-176 — Lifecycle Events System.

Meta-events are emitted BY the EventRegistry, not by domain code.
They report internal system conditions (subscriber failures, etc.).
"""
from dataclasses import dataclass
from parrot.core.events.lifecycle.base import LifecycleEvent


@dataclass(frozen=True)
class SubscriberErrorEvent(LifecycleEvent):
    """Emitted to the global registry when a subscriber raises.

    Part of the error isolation model (B): subscriber exceptions are caught,
    logged, and reported as SubscriberErrorEvents to the global registry
    instead of propagating to the caller.

    NEVER re-routed back to a subscriber that is itself failing (guarded
    by a recursion guard in EventRegistry to prevent infinite loops).

    Attributes:
        failed_subscriber: String representation of the failing subscriber
            callback (``repr(callback)``).
        original_event_class: Class name of the event that triggered the
            failing subscriber.
        error_type: ``type(exc).__name__`` of the exception.
        error_message: String representation of the exception.
        traceback: Full traceback string from ``traceback.format_exc()``.
    """

    failed_subscriber: str = ""
    original_event_class: str = ""
    error_type: str = ""
    error_message: str = ""
    traceback: str = ""
