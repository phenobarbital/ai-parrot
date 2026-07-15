---
type: Wiki Summary
title: parrot.knowledge.ontology.graph_store
id: mod:parrot.knowledge.ontology.graph_store
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: ArangoDB wrapper for ontology graph operations.
relates_to:
- concept: class:parrot.knowledge.ontology.graph_store.OntologyGraphStore
  rel: defines
- concept: class:parrot.knowledge.ontology.graph_store.UpsertResult
  rel: defines
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
---

# `parrot.knowledge.ontology.graph_store`

ArangoDB wrapper for ontology graph operations.

Provides tenant-isolated graph operations: database/collection initialization,
AQL traversals, node upsert, and edge creation. Uses ``asyncdb.AsyncDB``
for all database operations, consistent with ``parrot.stores.arango``.

## Classes

- **`UpsertResult(BaseModel)`** — Result of a batch upsert operation.
- **`OntologyGraphStore`** — ArangoDB wrapper for ontology graph operations.
