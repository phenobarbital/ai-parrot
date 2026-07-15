---
type: Wiki Entity
title: BeforeInvokeEvent
id: class:parrot.core.events.lifecycle.events.invoke.BeforeInvokeEvent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Emitted just before an agent invocation begins.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# BeforeInvokeEvent

Defined in [`parrot.core.events.lifecycle.events.invoke`](../summaries/mod:parrot.core.events.lifecycle.events.invoke.md).

```python
class BeforeInvokeEvent(LifecycleEvent)
```

Emitted just before an agent invocation begins.

Attributes:
    agent_name: Name of the invoking agent.
    method: The method being called (``"ask"``, ``"ask_stream"``,
        ``"conversation"``).
    question: The user's input question (may be truncated for safety).
    user_id: Optional user identifier.
    session_id: Optional session identifier.
