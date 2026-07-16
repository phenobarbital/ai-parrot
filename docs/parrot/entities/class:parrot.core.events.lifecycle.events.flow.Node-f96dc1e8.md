---
type: Wiki Entity
title: NodeFailedEvent
id: class:parrot.core.events.lifecycle.events.flow.NodeFailedEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted when a node fails after exhausting its retry budget.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# NodeFailedEvent

Defined in [`parrot.core.events.lifecycle.events.flow`](../summaries/mod:parrot.core.events.lifecycle.events.flow.md).

```python
class NodeFailedEvent(LifecycleEvent)
```

Emitted when a node fails after exhausting its retry budget.

Attributes:
    flow_name: Name of the owning ``AgentsFlow``.
    node_id: Graph-unique node identifier.
    run_id: Caller-supplied run identifier.
    duration_ms: Wall-clock time of the failing attempt in milliseconds.
    error_type: ``type(exc).__name__`` of the exception.
    error_message: String representation of the exception.
