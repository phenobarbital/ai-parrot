---
type: Wiki Entity
title: NodeCompletedEvent
id: class:parrot.core.events.lifecycle.events.flow.NodeCompletedEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted when a node's ``execute()`` returns successfully.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# NodeCompletedEvent

Defined in [`parrot.core.events.lifecycle.events.flow`](../summaries/mod:parrot.core.events.lifecycle.events.flow.md).

```python
class NodeCompletedEvent(LifecycleEvent)
```

Emitted when a node's ``execute()`` returns successfully.

NOT emitted when the node raises (``NodeFailedEvent`` is used instead).

Attributes:
    flow_name: Name of the owning ``AgentsFlow``.
    node_id: Graph-unique node identifier.
    run_id: Caller-supplied run identifier.
    duration_ms: Wall-clock time of the (last) execution attempt in
        milliseconds.
