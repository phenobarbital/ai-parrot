---
type: Wiki Entity
title: NodeSkippedEvent
id: class:parrot.core.events.lifecycle.events.flow.NodeSkippedEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted when OR-join skip-propagation marks a node as never-run.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# NodeSkippedEvent

Defined in [`parrot.core.events.lifecycle.events.flow`](../summaries/mod:parrot.core.events.lifecycle.events.flow.md).

```python
class NodeSkippedEvent(LifecycleEvent)
```

Emitted when OR-join skip-propagation marks a node as never-run.

Only produced by the explicit-edge scheduler mode: the node's incoming
edges all resolved but none fired (untaken branch, or upstream failure
routed elsewhere).

Attributes:
    flow_name: Name of the owning ``AgentsFlow``.
    node_id: Graph-unique node identifier.
    run_id: Caller-supplied run identifier.
