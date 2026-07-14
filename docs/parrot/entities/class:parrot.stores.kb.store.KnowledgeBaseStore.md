---
type: Wiki Entity
title: KnowledgeBaseStore
id: class:parrot.stores.kb.store.KnowledgeBaseStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Lightweight in-memory store for validated facts.
---

# KnowledgeBaseStore

Defined in [`parrot.stores.kb.store`](../summaries/mod:parrot.stores.kb.store.md).

```python
class KnowledgeBaseStore
```

Lightweight in-memory store for validated facts.

Args:
    embedding_model: HuggingFace model name (e.g. ``"all-MiniLM-L6-v2"``).
        The model is loaded lazily on first ``add_facts()`` / ``search_facts()``
        call via ``EmbeddingRegistry``.
    dimension: Embedding vector dimension (must match the model output).
    index_type: FAISS index type — ``"Flat"`` (exact) or ``"HNSW"``
        (approximate, faster for larger KBs).

## Methods

- `def embeddings(self)` — Return the cached embedding model, loading it on first access.
- `def embeddings(self, value)` — Allow direct assignment (for testing / backwards compat).
- `async def add_fact(self, fact: Dict[str, Any])` — Add a single validated fact to the KB.
- `async def add_facts(self, facts: List[Dict[str, Any]])` — Add validated facts to the KB.
- `async def search_facts(self, query: str, k: int=5, score_threshold: float=0.5) -> List[Dict[str, Any]]` — Ultra-fast fact retrieval.
- `def get_facts_by_category(self, category: str) -> List[Dict]` — Retrieve all facts in a category.
- `def get_entity_facts(self, entity: str) -> List[Dict]` — Get all facts related to an entity.
- `async def close(self)` — Cleanup resources if needed.
