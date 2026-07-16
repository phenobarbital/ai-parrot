---
type: Wiki Entity
title: LoggingSubscriber
id: class:parrot.core.events.lifecycle.subscribers.logging.LoggingSubscriber
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: EventProvider that logs every ``LifecycleEvent`` at a configurable level.
---

# LoggingSubscriber

Defined in [`parrot.core.events.lifecycle.subscribers.logging`](../summaries/mod:parrot.core.events.lifecycle.subscribers.logging.md).

```python
class LoggingSubscriber
```

EventProvider that logs every ``LifecycleEvent`` at a configurable level.

Conforms to the ``EventProvider`` Protocol (TASK-1188) by exposing a
synchronous ``register(registry)`` method.  One subscription to
``LifecycleEvent`` (the base class) is enough to capture every concrete
subclass.

Warning:
    Using ``level=logging.INFO`` (the default) on a streaming agent will
    generate thousands of log records per response — one per
    ``ClientStreamChunkEvent``.  In production, either set
    ``level=logging.DEBUG`` so records can be filtered out by the root
    logger, or use the ``where=`` predicate on your subscription to exclude
    ``ClientStreamChunkEvent`` before adding the subscriber.

Args:
    level: Python logging level (default ``logging.INFO``).
    logger_name: Name of the logger to write to (default ``"parrot.lifecycle"``).

Example::

    from parrot.core.events.lifecycle.subscribers.logging import LoggingSubscriber

    # Recommended for production — set level=DEBUG to avoid stream chunk noise.
    registry.add_provider(LoggingSubscriber(level=logging.DEBUG))

## Methods

- `def register(self, registry: 'EventRegistry') -> None` — Register one subscription that captures all LifecycleEvent subclasses.
