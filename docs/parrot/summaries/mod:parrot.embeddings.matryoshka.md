---
type: Wiki Summary
title: parrot.embeddings.matryoshka
id: mod:parrot.embeddings.matryoshka
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Matryoshka Representation Learning (MRL) truncation configuration.
relates_to:
- concept: class:parrot.embeddings.matryoshka.MatryoshkaConfig
  rel: defines
- concept: func:parrot.embeddings.matryoshka.validate_against_catalog
  rel: defines
- concept: mod:parrot.embeddings.catalog
  rel: references
- concept: mod:parrot.exceptions
  rel: references
---

# `parrot.embeddings.matryoshka`

Matryoshka Representation Learning (MRL) truncation configuration.

This module provides the operator-facing Pydantic model for the ``matryoshka``
sub-dict inside ``vector_store_config['embedding_model']``, plus a
configure-time validator that rejects unsupported truncation dimensions before
any embedding work is performed.

Usage example::

    from parrot.embeddings.matryoshka import MatryoshkaConfig, validate_against_catalog

    cfg = MatryoshkaConfig(enabled=True, dimension=512)
    validate_against_catalog(cfg, "nomic-ai/nomic-embed-text-v1.5")  # passes silently

Shape inside ``vector_store_config``::

    {
        "embedding_model": {
            "model_name": "nomic-ai/nomic-embed-text-v1.5",
            "model_type": "huggingface",
            "matryoshka": {
                "enabled": true,
                "dimension": 512
            }
        }
    }

## Classes

- **`MatryoshkaConfig(BaseModel)`** — Operator-supplied Matryoshka truncation configuration.

## Functions

- `def validate_against_catalog(cfg: MatryoshkaConfig, model_name: str) -> None` — Raise ``ConfigError`` if ``cfg`` is not satisfiable for ``model_name``.
