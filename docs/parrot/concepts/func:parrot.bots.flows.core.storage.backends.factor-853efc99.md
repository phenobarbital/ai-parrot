---
type: Concept
title: get_result_storage()
id: func:parrot.bots.flows.core.storage.backends.factory.get_result_storage
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Resolve a ``ResultStorage`` instance.
---

# get_result_storage

```python
def get_result_storage(name_or_instance: Union[str, 'ResultStorage', None]=None) -> 'ResultStorage'
```

Resolve a ``ResultStorage`` instance.

Resolution precedence:
    1. ``ResultStorage`` instance → returned as-is.
    2. Non-empty string → looked up in the backend registry.
    3. ``None`` → falls back to env var ``CREW_RESULT_STORAGE``,
       then defaults to ``"documentdb"``.

Args:
    name_or_instance: A ``ResultStorage`` instance, a backend name string
        (``"redis"``, ``"postgres"``, ``"documentdb"``), or ``None``.

Returns:
    A ``ResultStorage`` instance.

Raises:
    ValueError: If the name is not found in the backend registry.
