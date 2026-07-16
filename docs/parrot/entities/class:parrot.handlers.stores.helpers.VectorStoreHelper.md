---
type: Wiki Entity
title: VectorStoreHelper
id: class:parrot.handlers.stores.helpers.VectorStoreHelper
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Public metadata endpoints for vector store configuration.
---

# VectorStoreHelper

Defined in [`parrot.handlers.stores.helpers`](../summaries/mod:parrot.handlers.stores.helpers.md).

```python
class VectorStoreHelper(BaseHandler)
```

Public metadata endpoints for vector store configuration.

All methods are static and return plain dicts/lists.
These are called by VectorStoreHandler.get() to serve
unauthenticated metadata endpoints.

## Methods

- `def supported_stores() -> dict` — Return supported vector store types.
- `def supported_embeddings() -> dict` — Return supported embedding model types.
- `def supported_loaders() -> dict` — Return supported file loaders as a clean extension→class_name mapping.
- `def supported_embedding_models(provider: str=None, use_case: str=None, metric: str=None, max_dims: int=None, hnsw_compatible: bool=None, requires_prefix: bool=None) -> List[Dict[str, Any]]` — Return the curated catalog of embedding models, optionally filtered.
- `def supported_use_cases() -> Dict[str, str]` — Return embedding use-case categories and descriptions.
- `def supported_index_types() -> list` — Return supported distance strategy / index types.
