---
type: Wiki Entity
title: InvokeFailedEvent
id: class:parrot.core.events.lifecycle.events.invoke.InvokeFailedEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted when an agent invocation raises an unhandled exception.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# InvokeFailedEvent

Defined in [`parrot.core.events.lifecycle.events.invoke`](../summaries/mod:parrot.core.events.lifecycle.events.invoke.md).

```python
class InvokeFailedEvent(LifecycleEvent)
```

Emitted when an agent invocation raises an unhandled exception.

AfterInvokeEvent is NOT emitted when this event fires.

Attributes:
    agent_name: Name of the invoking agent.
    method: The method that was called.
    duration_ms: Wall-clock time in milliseconds until failure.
    error_type: ``type(exc).__name__`` of the exception.
    error_message: String representation of the exception.
