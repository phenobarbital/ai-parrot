---
type: Wiki Entity
title: FlowStartedEvent
id: class:parrot.core.events.lifecycle.events.flow.FlowStartedEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted when ``AgentsFlow.run_flow()`` begins dispatching.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# FlowStartedEvent

Defined in [`parrot.core.events.lifecycle.events.flow`](../summaries/mod:parrot.core.events.lifecycle.events.flow.md).

```python
class FlowStartedEvent(LifecycleEvent)
```

Emitted when ``AgentsFlow.run_flow()`` begins dispatching.

Attributes:
    flow_name: Name of the ``AgentsFlow`` instance.
    run_id: Caller-supplied run identifier (empty when the flow is run
        outside a runner that mints one).
    node_count: Number of nodes materialized for this run.
