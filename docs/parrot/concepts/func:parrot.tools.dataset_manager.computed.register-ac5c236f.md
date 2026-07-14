---
type: Concept
title: register_computed_function()
id: func:parrot.tools.dataset_manager.computed.register_computed_function
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register a custom function in the computed-columns registry.
---

# register_computed_function

```python
def register_computed_function(name: str, fn: Callable) -> None
```

Register a custom function in the computed-columns registry.

Once registered, the function can be referenced by name in
``ComputedColumnDef.func``.

Args:
    name: Registry key (must be unique; overwrites existing entry).
    fn: Callable following the QuerySource pattern:
        ``fn(df, field, columns, **kwargs) -> df``.
