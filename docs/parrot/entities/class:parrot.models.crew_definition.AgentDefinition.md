---
type: Wiki Entity
title: AgentDefinition
id: class:parrot.models.crew_definition.AgentDefinition
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Definition of an agent in a crew.
---

# AgentDefinition

Defined in [`parrot.models.crew_definition`](../summaries/mod:parrot.models.crew_definition.md).

```python
class AgentDefinition(BaseModel)
```

Definition of an agent in a crew.

Attributes:
    agent_id: Unique identifier for the agent within this crew.
    agent_class: Agent class name used to resolve the concrete class
        (e.g. "BaseAgent", "Chatbot", "WebSearchAgent").
    name: Human-readable display name for the agent. Falls back to
        ``agent_id`` when not provided.
    config: Arbitrary agent configuration forwarded as ``**kwargs``
        to the agent constructor (e.g. ``llm``, ``model``,
        ``temperature``, provider-specific options).
    tools: List of tool names that this agent has access to.
    system_prompt: Optional system prompt to set on the agent after
        construction.
