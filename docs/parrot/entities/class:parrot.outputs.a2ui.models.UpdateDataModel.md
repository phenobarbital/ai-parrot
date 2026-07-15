---
type: Wiki Entity
title: UpdateDataModel
id: class:parrot.outputs.a2ui.models.UpdateDataModel
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: '``updateDataModel`` — patch a surface''s data model.'
relates_to:
- concept: class:parrot.outputs.a2ui.models.A2UIMessageBase
  rel: extends
---

# UpdateDataModel

Defined in [`parrot.outputs.a2ui.models`](../summaries/mod:parrot.outputs.a2ui.models.md).

```python
class UpdateDataModel(A2UIMessageBase)
```

``updateDataModel`` — patch a surface's data model.

``contents`` maps JSON-Pointer paths to values (e.g. ``{"/charts/blk-000": ...}``).
