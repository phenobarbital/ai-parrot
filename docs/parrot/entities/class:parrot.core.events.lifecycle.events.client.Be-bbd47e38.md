---
type: Wiki Entity
title: BeforeClientCallEvent
id: class:parrot.core.events.lifecycle.events.client.BeforeClientCallEvent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Emitted just before an LLM API call is made.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# BeforeClientCallEvent

Defined in [`parrot.core.events.lifecycle.events.client`](../summaries/mod:parrot.core.events.lifecycle.events.client.md).

```python
class BeforeClientCallEvent(LifecycleEvent)
```

Emitted just before an LLM API call is made.

Attributes:
    client_name: Provider identifier (``"anthropic"``, ``"openai"``, etc.).
    model: Model name/identifier being called.
    temperature: Sampling temperature (None if not configured).
    system_prompt_hash: SHA-256 hex of the system prompt. NEVER the prompt
        itself — this preserves privacy while enabling correlation.
    has_tools: True if tool definitions were included in the request.
    agent_name: ``AbstractBot.name`` of the invoking agent, or ``None``
        when called outside a bot invocation scope.  Set by the client
        from the ``current_agent_name`` ContextVar (FEAT-228).
        NEVER contains PII (user_id, session_id, prompt content).
