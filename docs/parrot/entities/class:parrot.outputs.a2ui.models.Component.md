---
type: Wiki Entity
title: Component
id: class:parrot.outputs.a2ui.models.Component
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A single node in an A2UI component adjacency list.
---

# Component

Defined in [`parrot.outputs.a2ui.models`](../summaries/mod:parrot.outputs.a2ui.models.md).

```python
class Component(BaseModel)
```

A single node in an A2UI component adjacency list.

Components form a flat adjacency list: ``children`` holds the *ids* of other
components in the same message (component-id links), not nested objects.

Attributes:
    id: Stable, deterministic component id (e.g. ``"blk-000"``).
    component: The catalog component type name (e.g. ``"Column"``, ``"Chart"``).
    properties: Declarative component properties; may contain binding
        expressions (``{"$bind": "/pointer"}``) whose syntax is validated here.
    children: Component-id references to child components.
