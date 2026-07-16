---
type: Wiki Entity
title: AgentStatusChangedEvent
id: class:parrot.core.events.lifecycle.events.agent.AgentStatusChangedEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted when the agent's status property changes.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# AgentStatusChangedEvent

Defined in [`parrot.core.events.lifecycle.events.agent`](../summaries/mod:parrot.core.events.lifecycle.events.agent.md).

```python
class AgentStatusChangedEvent(LifecycleEvent)
```

Emitted when the agent's status property changes.

old_status / new_status hold the AgentStatus enum member name
(uppercase string, e.g., ``"IDLE"``, ``"WORKING"``, ``"COMPLETED"``,
``"FAILED"``).

Attributes:
    agent_name: Name of the agent whose status changed.
    old_status: Previous status as uppercase enum name.
    new_status: New status as uppercase enum name.
