---
type: Wiki Entity
title: MoveField
id: class:parrot_formdesigner.api.operations.MoveField
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Move a field across (or within) sections.
---

# MoveField

Defined in [`parrot_formdesigner.api.operations`](../summaries/mod:parrot_formdesigner.api.operations.md).

```python
class MoveField(_OpBase)
```

Move a field across (or within) sections.

``from`` is a Python keyword, so the wire field is aliased to ``from_``.
Set ``model_config = ConfigDict(populate_by_name=True)`` so both the
alias and the field name are accepted.
