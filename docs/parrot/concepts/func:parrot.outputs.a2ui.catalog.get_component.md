---
type: Concept
title: get_component()
id: func:parrot.outputs.a2ui.catalog.get_component
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return the registered component for ``name``.
---

# get_component

```python
def get_component(name: str) -> RegisteredComponent
```

Return the registered component for ``name``.

Raises:
    KeyError: If ``name`` is not registered.
