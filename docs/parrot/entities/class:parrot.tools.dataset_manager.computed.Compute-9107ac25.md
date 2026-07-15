---
type: Wiki Entity
title: ComputedColumnDef
id: class:parrot.tools.dataset_manager.computed.ComputedColumnDef
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Definition of a computed column applied post-materialization.
---

# ComputedColumnDef

Defined in [`parrot.tools.dataset_manager.computed`](../summaries/mod:parrot.tools.dataset_manager.computed.md).

```python
class ComputedColumnDef(BaseModel)
```

Definition of a computed column applied post-materialization.

The function identified by ``func`` must be present in
``COMPUTED_FUNCTIONS`` at the time the column is applied.  Functions are
loaded lazily from the QuerySource catalog (if available) and always fall
back to the built-in implementations.

Attributes:
    name: Name of the new column to create in the DataFrame.
    func: Function name from the ``COMPUTED_FUNCTIONS`` registry.
    columns: Source column names that the function operates on.
    kwargs: Extra keyword arguments forwarded to the function.
    description: Human-readable description shown in the LLM guide and
        column metadata.
