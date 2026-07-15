---
type: Wiki Entity
title: A2AAgent
id: class:parrot.bots.a2a_agent.A2AAgent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: An AI-Parrot Agent with A2A capabilities.
relates_to:
- concept: class:parrot.a2a.server.A2AEnabledMixin
  rel: extends
- concept: class:parrot.bots.agent.BasicAgent
  rel: extends
---

# A2AAgent

Defined in [`parrot.bots.a2a_agent`](../summaries/mod:parrot.bots.a2a_agent.md).

```python
class A2AAgent(BasicAgent, A2AEnabledMixin)
```

An AI-Parrot Agent with A2A capabilities.

## Methods

- `async def configure(self)` — Configure the agent and initialize A2A server.
