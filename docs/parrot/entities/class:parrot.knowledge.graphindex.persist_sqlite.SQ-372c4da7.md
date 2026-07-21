---
type: Wiki Entity
title: SQLitePersistence
id: class:parrot.knowledge.graphindex.persist_sqlite.SQLitePersistence
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Per-tenant SQLite persistence backend for GraphIndex.
---

# SQLitePersistence

Defined in [`parrot.knowledge.graphindex.persist_sqlite`](../summaries/mod:parrot.knowledge.graphindex.persist_sqlite.md).

```python
class SQLitePersistence
```

Per-tenant SQLite persistence backend for GraphIndex.

Creates one ``<tenant_id>.db`` file per tenant inside ``db_dir``.
The schema is initialised automatically on first access.

The public API matches ``GraphIndexPersistence`` so the builder can
use either backend via dependency injection.  Additionally exposes
``is_stale()`` for incremental build support.

Args:
    db_dir: Directory where tenant ``.db`` files are stored.  Will
        be created if it does not exist.

## Methods

- `async def persist_graph(self, ctx: TenantContext, nodes: list[UniversalNode], edges: list[UniversalEdge]) -> dict[str, Any]` — Persist all nodes and edges for a tenant graph.
- `async def replace_document_slice(self, ctx: TenantContext, document_uri: str, nodes: list[UniversalNode], edges: list[UniversalEdge]) -> dict[str, Any]` — Atomically replace all nodes/edges for a single document.
- `async def is_stale(self, ctx: TenantContext, source_uri: str, mtime: float, sha1: str) -> bool` — Check whether a source file needs re-extraction.
