---
type: Concept
title: register_component()
id: func:parrot.outputs.a2ui.catalog.register_component
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register a catalog component under ``name``.
---

# register_component

```python
def register_component(name: str, *, requires_actions: bool=False, catalog_id: str=DEFAULT_CATALOG_ID) -> Callable[[type], type]
```

Register a catalog component under ``name``.

Enforces the mandatory lowering contract at registration time: a class without
a callable ``lower()`` cannot register (raises :class:`ComponentContractError`).

Args:
    name: The component type name used in envelopes (e.g. ``"Chart"``).
    requires_actions: Marks the component as action-bearing (D10b). LLM-produced
        envelopes containing it are rejected by :func:`validate_envelope`.
    catalog_id: Owning catalog id; defaults to the Parrot custom catalog.

Returns:
    The class decorator.

Raises:
    ComponentContractError: If the decorated class lacks a callable ``lower()``.
