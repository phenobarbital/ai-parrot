---
type: Wiki Summary
title: parrot.knowledge.graphindex.persist
id: mod:parrot.knowledge.graphindex.persist
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Persistence stage for GraphIndex.
relates_to:
- concept: class:parrot.knowledge.graphindex.persist.GraphIndexPersistence
  rel: defines
- concept: mod:parrot.knowledge.graphindex.meta_ontology
  rel: references
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
- concept: mod:parrot.knowledge.ontology.graph_store
  rel: references
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
---

# `parrot.knowledge.graphindex.persist`

Persistence stage for GraphIndex.

Writes assembled graph nodes and edges to ArangoDB via
``OntologyGraphStore`` and embeddings to pgvector.  Supports atomic
per-document replacement for incremental refresh via soft-delete-then-upsert.

## Classes

- **`GraphIndexPersistence`** — Persists GraphIndex nodes, edges, and embeddings to ArangoDB + pgvector.
