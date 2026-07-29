---
type: Wiki Entity
title: ListAvailableA2AAgentsTool
id: class:parrot.bots.flows.agents.a2a_orchestrator.ListAvailableA2AAgentsTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool that discovers available A2A agents from specified endpoints.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# ListAvailableA2AAgentsTool

Defined in [`parrot.bots.flows.agents.a2a_orchestrator`](../summaries/mod:parrot.bots.flows.agents.a2a_orchestrator.md).

```python
class ListAvailableA2AAgentsTool(AbstractTool)
```

Tool that discovers available A2A agents from specified endpoints.

This tool allows the LLM to dynamically discover what remote agents
are available for orchestration tasks.
