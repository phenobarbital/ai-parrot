---
type: Wiki Entity
title: ToolManagerReadyEvent
id: class:parrot.core.events.lifecycle.events.agent.ToolManagerReadyEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted after the ToolManager is fully populated.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# ToolManagerReadyEvent

Defined in [`parrot.core.events.lifecycle.events.agent`](../summaries/mod:parrot.core.events.lifecycle.events.agent.md).

```python
class ToolManagerReadyEvent(LifecycleEvent)
```

Emitted after the ToolManager is fully populated.

Attributes:
    agent_name: Name of the agent whose ToolManager is ready.
    tool_count: Number of tools registered.
    tool_names: Immutable tuple of registered tool names.
