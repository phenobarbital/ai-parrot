---
type: Wiki Entity
title: RoutingTrace
id: class:parrot.registry.capabilities.models.RoutingTrace
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Full trace of a routing session.
---

# RoutingTrace

Defined in [`parrot.registry.capabilities.models`](../summaries/mod:parrot.registry.capabilities.models.md).

```python
class RoutingTrace(BaseModel)
```

Full trace of a routing session.

Args:
    mode: Routing mode — "normal" (cascade) or "exhaustive" (all strategies).
    entries: Ordered list of trace entries for each strategy attempted.
    elapsed_ms: Total elapsed time for the full routing session.
