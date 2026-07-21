---
type: Wiki Entity
title: MapColumn
id: class:parrot.models.outputs.MapColumn
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per-column contract for a map layer (same vocabulary as TableColumn).
---

# MapColumn

Defined in [`parrot.models.outputs`](../summaries/mod:parrot.models.outputs.md).

```python
class MapColumn(BaseModel)
```

Per-column contract for a map layer (same vocabulary as TableColumn).

Carries the minimum information a frontend map library needs to
render a column correctly: the key name, its storage type, a human
label, and an optional display-format hint.

Attributes:
    name: Column key — must match a key in every data row dict /
        feature.properties.
    type: Storage type vocabulary: ``string`` | ``integer`` | ``number`` |
        ``boolean`` | ``date`` | ``datetime`` | ``time`` | ``duration`` | ``any``.
    title: Human-readable column label (defaults to ``name`` as-is; the
        renderer may refine it via a narrow LLM pass).
    format: Optional display hint for ambiguous columns:
        ``currency`` | ``percent`` | ``email`` | ``uri`` | ``enum`` |
        ``id`` | ``code``.
        This is a *hint* for the frontend — it does NOT change the base
        storage type.
