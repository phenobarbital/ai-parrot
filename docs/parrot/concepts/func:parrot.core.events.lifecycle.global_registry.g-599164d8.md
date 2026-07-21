---
type: Concept
title: get_global_registry()
id: func:parrot.core.events.lifecycle.global_registry.get_global_registry
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the process-wide singleton ``EventRegistry``.
---

# get_global_registry

```python
def get_global_registry() -> EventRegistry
```

Return the process-wide singleton ``EventRegistry``.

Lazily constructs the registry on first call.  Subsequent calls in the
same context return the same instance until a :func:`scope` block
replaces it.

The global registry is constructed with ``forward_to_global=False`` to
prevent infinite recursion (it must not forward events back to itself).

Returns:
    The current context's global ``EventRegistry`` instance.
