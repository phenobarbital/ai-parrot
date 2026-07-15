---
type: Wiki Entity
title: TraceEntry
id: class:parrot.registry.capabilities.models.TraceEntry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: One step in the routing trace.
---

# TraceEntry

Defined in [`parrot.registry.capabilities.models`](../summaries/mod:parrot.registry.capabilities.models.md).

```python
class TraceEntry(BaseModel)
```

One step in the routing trace.

Args:
    routing_type: Strategy attempted in this step.
    produced_context: True if this step contributed to the final context.
    context_snippet: Brief excerpt of the produced context (if any).
    error: Error message if this step failed.
    elapsed_ms: Time taken for this step in milliseconds.
    store_rankings: Optional store-level routing detail populated by
        ``StoreRouter`` (FEAT-111).  ``None`` when the store router is not
        active — backward compatible with all existing callers.
