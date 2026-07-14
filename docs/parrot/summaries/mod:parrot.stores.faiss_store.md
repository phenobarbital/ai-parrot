---
type: Wiki Summary
title: parrot.stores.faiss_store
id: mod:parrot.stores.faiss_store
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'FAISSStore: In-memory Vector Store implementation using FAISS.'
relates_to:
- concept: class:parrot.stores.faiss_store.FAISSStore
  rel: defines
- concept: mod:parrot.stores.abstract
  rel: references
- concept: mod:parrot.stores.models
  rel: references
- concept: mod:parrot.utils.faiss_logging
  rel: references
---

# `parrot.stores.faiss_store`

FAISSStore: In-memory Vector Store implementation using FAISS.

Provides high-performance vector similarity search with:
- In-memory vector storage with FAISS indexes
- Multiple distance metrics (Cosine, L2, Inner Product)
- CPU-only execution (GPU support removed)
- MMR (Maximal Marginal Relevance) search
- Metadata filtering
- Collection management
- Async context manager support

## Classes

- **`FAISSStore(AbstractStore)`** — An in-memory FAISS vector store implementation, completely independent of Langchain.
