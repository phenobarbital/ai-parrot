---
type: Wiki Entity
title: Agent
id: class:parrot.bots.agent.Agent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A general-purpose agent with no additional tools.
relates_to:
- concept: class:parrot.bots.agent.BasicAgent
  rel: extends
---

# Agent

Defined in [`parrot.bots.agent`](../summaries/mod:parrot.bots.agent.md).

```python
class Agent(BasicAgent)
```

A general-purpose agent with no additional tools.

## Methods

- `def agent_tools(self) -> List[AbstractTool]` — Return the agent-specific tools.
