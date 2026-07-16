---
type: Wiki Entity
title: SubscriberErrorEvent
id: class:parrot.core.events.lifecycle.meta.SubscriberErrorEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted to the global registry when a subscriber raises.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# SubscriberErrorEvent

Defined in [`parrot.core.events.lifecycle.meta`](../summaries/mod:parrot.core.events.lifecycle.meta.md).

```python
class SubscriberErrorEvent(LifecycleEvent)
```

Emitted to the global registry when a subscriber raises.

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

## Methods

- `def to_dict(self) -> dict[str, Any]` — Serialize to a JSON-compatible dict with traceback truncation.
