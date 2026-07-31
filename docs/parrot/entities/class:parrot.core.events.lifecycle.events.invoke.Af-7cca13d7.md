---
type: Wiki Entity
title: AfterInvokeEvent
id: class:parrot.core.events.lifecycle.events.invoke.AfterInvokeEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted after a successful agent invocation completes.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# AfterInvokeEvent

Defined in [`parrot.core.events.lifecycle.events.invoke`](../summaries/mod:parrot.core.events.lifecycle.events.invoke.md).

```python
class AfterInvokeEvent(LifecycleEvent)
```

Emitted after a successful agent invocation completes.

NOT emitted when the invocation fails (InvokeFailedEvent is used instead).

Attributes:
    agent_name: Name of the invoking agent.
    method: The method that was called.
    duration_ms: Wall-clock time in milliseconds.
    input_tokens: Input token count (if available from the LLM response).
    output_tokens: Output token count (if available from the LLM response).
