---
type: Wiki Entity
title: ClientCallFailedEvent
id: class:parrot.core.events.lifecycle.events.client.ClientCallFailedEvent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Emitted when an LLM API call raises an exception.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# ClientCallFailedEvent

Defined in [`parrot.core.events.lifecycle.events.client`](../summaries/mod:parrot.core.events.lifecycle.events.client.md).

```python
class ClientCallFailedEvent(LifecycleEvent)
```

Emitted when an LLM API call raises an exception.

AfterClientCallEvent is NOT emitted when this fires.

Attributes:
    client_name: Provider identifier.
    model: Model name/identifier.
    duration_ms: Wall-clock time in milliseconds until failure.
    error_type: ``type(exc).__name__`` of the exception.
    error_message: String representation of the exception.
    agent_name: ``AbstractBot.name`` of the invoking agent, or ``None``
        when called outside a bot invocation scope.  Set by the client
        from the ``current_agent_name`` ContextVar (FEAT-228).
        NEVER contains PII (user_id, session_id, prompt content).
