---
type: Wiki Summary
title: parrot.stores.models
id: mod:parrot.stores.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Store data models.
relates_to:
- concept: class:parrot.stores.models.DistanceStrategy
  rel: defines
- concept: class:parrot.stores.models.Document
  rel: defines
- concept: mod:parrot.models.stores
  rel: references
---

# `parrot.stores.models`

Store data models.

``SearchResult`` and ``StoreConfig`` moved to :mod:`parrot.models.stores`
(the dependency-free core models package) so that consumers can import the
data contracts without triggering ``parrot.stores.__init__`` (which pulls in
``AbstractStore`` and the heavy store/embedding backends). They are
re-exported here for backward compatibility — existing
``from parrot.stores.models import SearchResult, StoreConfig`` keeps working.

## Classes

- **`Document(BaseModel)`** — A simple document model for adding data to the vector store.
- **`DistanceStrategy(str, Enum)`** — Enumerator of the Distance strategies for calculating distances
