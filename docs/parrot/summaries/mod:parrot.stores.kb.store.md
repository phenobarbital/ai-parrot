---
type: Wiki Summary
title: parrot.stores.kb.store
id: mod:parrot.stores.kb.store
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: KnowledgeBaseStore — In-memory fact store with FAISS-backed similarity search.
relates_to:
- concept: class:parrot.stores.kb.store.KnowledgeBaseStore
  rel: defines
- concept: mod:parrot.embeddings
  rel: references
- concept: mod:parrot.utils.faiss_logging
  rel: references
---

# `parrot.stores.kb.store`

KnowledgeBaseStore — In-memory fact store with FAISS-backed similarity search.

Embedding models are loaded lazily via ``EmbeddingRegistry`` on first access to
``self.embeddings``.  Construction no longer loads a ``SentenceTransformer``
directly, eliminating 5-30 s startup latency when the KB is never queried.

Two ``KnowledgeBaseStore`` instances sharing the same ``embedding_model`` name
will reuse a single cached ``EmbeddingModel`` object from the registry.

## Classes

- **`KnowledgeBaseStore`** — Lightweight in-memory store for validated facts.
