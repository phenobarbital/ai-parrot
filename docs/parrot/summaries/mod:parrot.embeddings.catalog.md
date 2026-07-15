---
type: Wiki Summary
title: parrot.embeddings.catalog
id: mod:parrot.embeddings.catalog
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Curated catalog of supported embedding models.
relates_to:
- concept: class:parrot.embeddings.catalog.EmbeddingModelEntry
  rel: defines
- concept: func:parrot.embeddings.catalog.get_embedding_models
  rel: defines
- concept: func:parrot.embeddings.catalog.get_model_recommendations
  rel: defines
- concept: func:parrot.embeddings.catalog.get_use_cases
  rel: defines
---

# `parrot.embeddings.catalog`

Curated catalog of supported embedding models.

Single source of truth for all embedding models available in the system.
Add new models here — they become available to APIs and frontends automatically.

Each entry includes a ``use_case`` list so consumers can filter models by
intended workload (similarity, retrieval, clustering, multilingual, code,
qa, long-context, instruct, asymmetric, symmetric).

Schema validation is performed at module import time via ``EmbeddingModelEntry``
(Pydantic v2). The runtime object remains a plain ``list[dict]`` for
JSON-serialisation compatibility with the consumer API.

## Classes

- **`EmbeddingModelEntry(BaseModel)`** — Validation schema for a single catalog entry.

## Functions

- `def get_embedding_models(provider: Optional[str]=None, use_case: Optional[str]=None, metric: Optional[str]=None, max_dims: Optional[int]=None, hnsw_compatible: Optional[bool]=None, requires_prefix: Optional[bool]=None) -> List[Dict[str, Any]]` — Return the curated list of embedding models, optionally filtered.
- `def get_use_cases() -> Dict[str, str]` — Return available use-case categories and their descriptions.
- `def get_model_recommendations(model_name: Optional[str]) -> Optional[Dict[str, Any]]` — Return per-model retrieval recommendations from the catalog.
