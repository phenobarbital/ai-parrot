---
type: Wiki Entity
title: AgentConfiguredEvent
id: class:parrot.core.events.lifecycle.events.agent.AgentConfiguredEvent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Emitted at the end of AbstractBot.configure().
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# AgentConfiguredEvent

Defined in [`parrot.core.events.lifecycle.events.agent`](../summaries/mod:parrot.core.events.lifecycle.events.agent.md).

```python
class AgentConfiguredEvent(LifecycleEvent)
```

Emitted at the end of AbstractBot.configure().

Attributes:
    agent_name: Name of the configured agent.
    llm_provider: String identifying the LLM provider (e.g., ``"anthropic"``).
    llm_model: Model name/identifier used by the configured LLM.
    has_vector_store: True if a vector store is wired to the agent.
