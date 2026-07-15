---
type: Wiki Entity
title: NodeStartedEvent
id: class:parrot.core.events.lifecycle.events.flow.NodeStartedEvent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Emitted when the scheduler dispatches a node.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# NodeStartedEvent

Defined in [`parrot.core.events.lifecycle.events.flow`](../summaries/mod:parrot.core.events.lifecycle.events.flow.md).

```python
class NodeStartedEvent(LifecycleEvent)
```

Emitted when the scheduler dispatches a node.

Attributes:
    flow_name: Name of the owning ``AgentsFlow``.
    node_id: Graph-unique node identifier.
    run_id: Caller-supplied run identifier.
