---
type: Wiki Summary
title: parrot.models.stores
id: mod:parrot.models.stores
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Store-identifier and store data models.
relates_to:
- concept: class:parrot.models.stores.SearchResult
  rel: defines
- concept: class:parrot.models.stores.StoreConfig
  rel: defines
- concept: class:parrot.models.stores.StoreType
  rel: defines
---

# `parrot.models.stores`

Store-identifier and store data models.

Lightweight, dependency-free models for the vector/graph stores supported
by AI-Parrot. Lives in ``parrot.models`` (core) so that the store-routing
registry, bots and tools can reference store identifiers and the shared
data contracts (``StoreConfig``, ``SearchResult``) **without** importing
from ``parrot.stores`` — whose package ``__init__`` eagerly pulls in
``AbstractStore`` → ``parrot.embeddings`` → ``parrot.conf`` …  Importing
those models from here keeps the dependency graph acyclic and avoids the
heavy store backends (which now ship from ``ai-parrot-embeddings``).

``parrot.stores.models`` re-exports ``StoreConfig`` and ``SearchResult``
from this module for backward compatibility.

## Classes

- **`StoreType(Enum)`** — DB Store type — source of truth for store identifiers.
- **`SearchResult(BaseModel)`** — Data model for a single document returned from a vector search.
- **`StoreConfig`** — Vector Store configuration dataclass.
