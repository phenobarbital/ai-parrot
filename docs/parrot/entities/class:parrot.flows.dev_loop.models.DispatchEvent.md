---
type: Wiki Entity
title: DispatchEvent
id: class:parrot.flows.dev_loop.models.DispatchEvent
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Envelope for stream-json events published to Redis.
---

# DispatchEvent

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class DispatchEvent(BaseModel)
```

Envelope for stream-json events published to Redis.

The dispatcher wraps every SDK message and every lifecycle transition
in a ``DispatchEvent`` and ``XADD``s it to
``flow:{run_id}:dispatch:{node_id}``. The streaming multiplexer
consumes the same envelope on the way out to the UI.
