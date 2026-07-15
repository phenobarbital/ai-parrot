---
type: Wiki Entity
title: GraphIndexPersistence
id: class:parrot.knowledge.graphindex.persist.GraphIndexPersistence
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Persists GraphIndex nodes, edges, and embeddings to ArangoDB + pgvector.
---

# GraphIndexPersistence

Defined in [`parrot.knowledge.graphindex.persist`](../summaries/mod:parrot.knowledge.graphindex.persist.md).

```python
class GraphIndexPersistence
```

Persists GraphIndex nodes, edges, and embeddings to ArangoDB + pgvector.

Provides per-tenant locking to prevent race conditions during the
soft-delete-then-upsert sequence in ``replace_document_slice``.

Args:
    graph_store: An initialised ``OntologyGraphStore`` instance.

## Methods

- `async def persist_graph(self, ctx: TenantContext, nodes: list[UniversalNode], edges: list[UniversalEdge]) -> dict[str, Any]` — Persist all nodes and edges to ArangoDB.
- `async def replace_document_slice(self, ctx: TenantContext, document_uri: str, nodes: list[UniversalNode], edges: list[UniversalEdge]) -> dict[str, Any]` — Atomic per-document replacement: soft-delete old slice, upsert new.
