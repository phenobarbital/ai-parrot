---
type: Concept
title: get_computed_function()
id: func:parrot.tools.dataset_manager.computed.get_computed_function
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Look up a function by name from the registry.
---

# get_computed_function

```python
def get_computed_function(name: str) -> Optional[Callable]
```

Look up a function by name from the registry.

Lazily loads built-ins and QuerySource functions on the first call.

Args:
    name: Function name to look up.

Returns:
    The callable if found, or ``None`` if the name is not registered.
