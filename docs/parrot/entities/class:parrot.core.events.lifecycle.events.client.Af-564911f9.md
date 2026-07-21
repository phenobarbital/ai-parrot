---
type: Wiki Entity
title: AfterClientCallEvent
id: class:parrot.core.events.lifecycle.events.client.AfterClientCallEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted after a successful LLM API call completes.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# AfterClientCallEvent

Defined in [`parrot.core.events.lifecycle.events.client`](../summaries/mod:parrot.core.events.lifecycle.events.client.md).

```python
class AfterClientCallEvent(LifecycleEvent)
```

Emitted after a successful LLM API call completes.

NOT emitted when the call fails (ClientCallFailedEvent is used instead).

Attributes:
    client_name: Provider identifier.
    model: Model name/identifier.
    duration_ms: Wall-clock time in milliseconds.
    input_tokens: Input token count (provider-dependent; may be None).
    output_tokens: Output token count (provider-dependent; may be None).
    finish_reason: Stop reason returned by the provider (e.g., ``"stop"``,
        ``"max_tokens"``). May be None.
    agent_name: ``AbstractBot.name`` of the invoking agent, or ``None``
        when called outside a bot invocation scope.  Set by the client
        from the ``current_agent_name`` ContextVar (FEAT-228).
        NEVER contains PII (user_id, session_id, prompt content).
