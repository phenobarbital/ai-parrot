---
type: Wiki Entity
title: CreateSurface
id: class:parrot.outputs.a2ui.models.CreateSurface
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: '``createSurface`` — create a UI surface, optionally with inline content.'
relates_to:
- concept: class:parrot.outputs.a2ui.models.A2UIMessageBase
  rel: extends
---

# CreateSurface

Defined in [`parrot.outputs.a2ui.models`](../summaries/mod:parrot.outputs.a2ui.models.md).

```python
class CreateSurface(A2UIMessageBase)
```

``createSurface`` — create a UI surface, optionally with inline content.

v1.0 allows a one-shot, SSR-friendly surface by carrying inline ``components``
and an initial ``data_model`` in the same message.
