"""Meta-events for error isolation (model B).

FEAT-176 — Lifecycle Events System.

Meta-events are emitted BY the EventRegistry, not by domain code.
They report internal system conditions (subscriber failures, etc.).
"""
from dataclasses import dataclass
from typing import Any

from parrot.core.events.lifecycle.base import LifecycleEvent


@dataclass(frozen=True)
class SubscriberErrorEvent(LifecycleEvent):
    """Emitted to the global registry when a subscriber raises.

    Part of the error isolation model (B): subscriber exceptions are caught,
    logged, and reported as SubscriberErrorEvents to the global registry
    instead of propagating to the caller.

    NEVER re-routed back to a subscriber that is itself failing (guarded
    by a recursion guard in EventRegistry to prevent infinite loops).

    Note:
        The ``traceback`` field is truncated to the last 20 lines in
        ``to_dict()`` to prevent accidental secret exposure in webhook
        payloads (e.g., environment variables printed in tracebacks).

    Attributes:
        failed_subscriber: String representation of the failing subscriber
            callback (``repr(callback)``).
        original_event_class: Class name of the event that triggered the
            failing subscriber.
        error_type: ``type(exc).__name__`` of the exception.
        error_message: String representation of the exception.
        traceback: Full traceback string from ``traceback.format_exc()``.
            Truncated to the last 20 lines in ``to_dict()`` output.
    """

    failed_subscriber: str = ""
    original_event_class: str = ""
    error_type: str = ""
    error_message: str = ""
    traceback: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict with traceback truncation.

        Extends the base ``to_dict()`` to truncate the ``traceback`` field to
        the last 20 lines.  This prevents accidental exposure of secrets that
        may appear in long tracebacks when the event is forwarded to webhook
        payloads or external observability backends.

        Returns:
            A dict where every value is JSON-serializable, with ``traceback``
            limited to the last 20 lines.
        """
        d = super().to_dict()
        if self.traceback:
            lines = self.traceback.splitlines()
            d["traceback"] = (
                "\n".join(lines[-20:]) if len(lines) > 20 else self.traceback
            )
        return d
