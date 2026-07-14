---
type: Wiki Entity
title: AgentTool
id: class:parrot.tools.agent.AgentTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Wraps any BasicAgent/AbstractBot as a tool for use by other agents.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# AgentTool

Defined in [`parrot.tools.agent`](../summaries/mod:parrot.tools.agent.md).

```python
class AgentTool(AbstractTool)
```

Wraps any BasicAgent/AbstractBot as a tool for use by other agents.

- Schema includes "parameters" key for Google GenAI compatibility
- Uses Pydantic args_schema for validation
- Accepts all args as **kwargs in _execute()

## Methods

- `def get_schema(self) -> Dict[str, Any]` — Return the tool schema in the format expected by Google GenAI.
- `def get_usage_stats(self) -> Dict[str, Any]` — Get usage statistics for this agent tool.
