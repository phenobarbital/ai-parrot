---
type: Wiki Summary
title: parrot.stores.arango
id: mod:parrot.stores.arango
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'ArangoDBStore: Vector Store implementation for ArangoDB.'
relates_to:
- concept: class:parrot.stores.arango.ArangoDBStore
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.stores.abstract
  rel: references
- concept: mod:parrot.stores.models
  rel: references
---

# `parrot.stores.arango`

ArangoDBStore: Vector Store implementation for ArangoDB.

Provides comprehensive vector storage with graph support, including:
- Database and collection management
- Graph creation and management
- Document operations with upsert support
- Vector similarity search
- Full-text search (BM25)
- Hybrid search (vector + text)
- Graph-enhanced retrieval

## Classes

- **`ArangoDBStore(AbstractStore)`** — ArangoDB Vector Store with native graph support.
