---
type: Wiki Entity
title: MatryoshkaConfig
id: class:parrot.embeddings.matryoshka.MatryoshkaConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Operator-supplied Matryoshka truncation configuration.
---

# MatryoshkaConfig

Defined in [`parrot.embeddings.matryoshka`](../summaries/mod:parrot.embeddings.matryoshka.md).

```python
class MatryoshkaConfig(BaseModel)
```

Operator-supplied Matryoshka truncation configuration.

Shape::

    {"enabled": True, "dimension": 512}

Validation lives in :func:`validate_against_catalog`, which checks that
the chosen ``dimension`` is in the model's ``matryoshka_dimensions`` list.

Attributes:
    enabled: When ``True``, truncation is active and ``dimension`` is
        required.  Defaults to ``False`` (no truncation).
    dimension: Target truncation dimension.  Must be a positive integer
        and must appear in the catalog's ``matryoshka_dimensions`` list
        for the requested model.  Required when ``enabled`` is ``True``.
