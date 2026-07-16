---
type: Concept
title: list_computed_functions()
id: func:parrot.tools.dataset_manager.computed.list_computed_functions
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return a sorted list of all registered function names.
---

# list_computed_functions

```python
def list_computed_functions() -> List[str]
```

Return a sorted list of all registered function names.

Lazily loads built-ins and QuerySource functions on the first call.

Returns:
    Sorted list of function name strings.
