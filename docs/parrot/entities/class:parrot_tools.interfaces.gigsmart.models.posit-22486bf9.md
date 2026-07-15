---
type: Wiki Entity
title: Position
id: class:parrot_tools.interfaces.gigsmart.models.position.Position
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A GigSmart organisation position template.
---

# Position

Defined in [`parrot_tools.interfaces.gigsmart.models.position`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.position.md).

```python
class Position(BaseModel)
```

A GigSmart organisation position template.

Args:
    id: Opaque prefixed position ID (e.g. ``"pos_..."``).
    name: Position display name.
    description: Optional longer description.
    pay_rate: ISO-4217 money scalar (e.g. ``"20.00"``).
    created_at: Optional creation timestamp.
