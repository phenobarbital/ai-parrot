---
type: Wiki Entity
title: FlowLifecycleAdapter
id: class:parrot.bots.flows.flow.telemetry.FlowLifecycleAdapter
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Node-event listener that emits typed FEAT-176 lifecycle events.
---

# FlowLifecycleAdapter

Defined in [`parrot.bots.flows.flow.telemetry`](../summaries/mod:parrot.bots.flows.flow.telemetry.md).

```python
class FlowLifecycleAdapter
```

Node-event listener that emits typed FEAT-176 lifecycle events.

Attach to an ``AgentsFlow`` via the constructor's ``on_node_event``
parameter or :meth:`AgentsFlow.add_node_event_listener`. The adapter is
synchronous (events are scheduled with ``EventRegistry.emit_nowait``)
and never raises — the engine additionally shields listeners.

Args:
    registry: Target ``EventRegistry``. ``None`` (default) resolves the
        process-wide global registry lazily on first event, matching the
        ``EventEmitterMixin`` default behaviour.
