---
type: Wiki Entity
title: A2UIMessageBase
id: class:parrot.outputs.a2ui.models.A2UIMessageBase
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Base for every A2UI v1.0 wire message.
---

# A2UIMessageBase

Defined in [`parrot.outputs.a2ui.models`](../summaries/mod:parrot.outputs.a2ui.models.md).

```python
class A2UIMessageBase(BaseModel)
```

Base for every A2UI v1.0 wire message.

Deliberately declares no ``version`` field — the protocol version is owned
exclusively by :mod:`parrot.outputs.a2ui.serialization`.
