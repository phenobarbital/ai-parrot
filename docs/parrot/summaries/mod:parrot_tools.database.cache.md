---
type: Wiki Summary
title: parrot_tools.database.cache
id: mod:parrot_tools.database.cache
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot_tools.database.cache
relates_to:
- concept: class:parrot_tools.database.cache.SchemaMetadataCache
  rel: defines
- concept: mod:parrot.stores.abstract
  rel: references
- concept: mod:parrot.stores.faiss_store
  rel: references
- concept: mod:parrot.stores.models
  rel: references
- concept: mod:parrot_tools.database.models
  rel: references
---

# `parrot_tools.database.cache`

## Classes

- **`SchemaMetadataCache`** — Two-tier caching: LRU (hot data) + Optional Vector Store (cold/searchable data).
