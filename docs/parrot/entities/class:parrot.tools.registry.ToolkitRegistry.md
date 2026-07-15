---
type: Wiki Entity
title: ToolkitRegistry
id: class:parrot.tools.registry.ToolkitRegistry
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Registry for supported toolkits with lazy loading.
---

# ToolkitRegistry

Defined in [`parrot.tools.registry`](../summaries/mod:parrot.tools.registry.md).

```python
class ToolkitRegistry
```

Registry for supported toolkits with lazy loading.

.. deprecated::
    Use ``ToolManager`` with discovery instead. This class is
    maintained for backward compatibility.

## Methods

- `def get_registry(cls) -> Dict[str, Type['AbstractToolkit']]` — Get the toolkit registry, initializing lazily if needed.
- `def get(cls, name: str) -> Type['AbstractToolkit']` — Get a toolkit class by name.
- `def list_toolkits(cls) -> list` — List all available toolkit names.
- `def register(cls, name: str, toolkit_class: Type['AbstractToolkit']) -> None` — Register a custom toolkit.
