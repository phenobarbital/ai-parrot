---
type: Concept
title: validate_against_catalog()
id: func:parrot.embeddings.matryoshka.validate_against_catalog
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raise ``ConfigError`` if ``cfg`` is not satisfiable for ``model_name``.
---

# validate_against_catalog

```python
def validate_against_catalog(cfg: MatryoshkaConfig, model_name: str) -> None
```

Raise ``ConfigError`` if ``cfg`` is not satisfiable for ``model_name``.

Reads ``EMBEDDING_MODELS`` to find the model entry, then checks:

1. The entry exists in the catalog.
2. The entry declares a non-empty ``matryoshka_dimensions`` list.
3. ``cfg.dimension`` is in that list.

When ``cfg.enabled`` is ``False``, the function returns ``None``
immediately — no catalog lookup is performed. This preserves backward
compatibility for bots that do not opt in to truncation.

Args:
    cfg: Parsed ``MatryoshkaConfig`` instance.
    model_name: Canonical model identifier (e.g.
        ``"nomic-ai/nomic-embed-text-v1.5"``).

Returns:
    ``None`` on success.

Raises:
    ConfigError: When Matryoshka is enabled but the model is not in the
        catalog, the model entry has no ``matryoshka_dimensions``, or
        ``cfg.dimension`` is not in the allowed list.
