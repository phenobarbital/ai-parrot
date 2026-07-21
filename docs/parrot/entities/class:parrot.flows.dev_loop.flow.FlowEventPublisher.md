---
type: Wiki Entity
title: FlowEventPublisher
id: class:parrot.flows.dev_loop.flow.FlowEventPublisher
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Publishes AgentsFlow node-lifecycle events to ``flow:{run_id}:flow``.
---

# FlowEventPublisher

Defined in [`parrot.flows.dev_loop.flow`](../summaries/mod:parrot.flows.dev_loop.flow.md).

```python
class FlowEventPublisher
```

Publishes AgentsFlow node-lifecycle events to ``flow:{run_id}:flow``.

Bound to ``AgentsFlow(on_node_event=...)``. The run_id is read from
the event's ``info["context"].shared_data["run_id"]`` (the engine
passes the run's FlowContext on every event, so concurrent runs on
the same flow instance publish to their own streams); a mutable
holder dict serves as fallback for callers that drive ``run_flow``
directly with an unseeded context.

The Redis connection is lazy and every failure is swallowed — event
publishing must never break a run.

Args:
    redis_url: Redis URL for the XADD calls.
    run_id_holder: Mutable mapping carrying the fallback ``"run_id"``.

## Methods

- `async def close(self) -> None` — Release the Redis connection pool.
