---
type: Wiki Entity
title: SQLiteGraphReader
id: class:parrot.knowledge.graphindex.sqlite_reader.SQLiteGraphReader
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Read-only navigator over a per-tenant SQLite GraphIndex artefact.
---

# SQLiteGraphReader

Defined in [`parrot.knowledge.graphindex.sqlite_reader`](../summaries/mod:parrot.knowledge.graphindex.sqlite_reader.md).

```python
class SQLiteGraphReader
```

Read-only navigator over a per-tenant SQLite GraphIndex artefact.

Call ``await reader.load()`` once before using any navigation or search
method.  The HOT navigation methods are synchronous (pure in-memory graph
traversal) while COLD methods (``search_symbols``, ``get_source``) are
async because they touch SQLite or the filesystem.

Args:
    db_path: Path to the ``<tenant_id>.db`` artefact produced by
        ``SQLitePersistence``.
    repo_root: Root directory to resolve ``source_uri`` paths for
        ``get_source``.  When ``None``, ``get_source`` falls back to
        returning the node's stored ``summary``.
    body_cache_size: Maximum entries in the COLD source-body LRU cache.
        Older entries are evicted when the cache is full.

## Methods

- `async def load(self) -> None` — Load topology (nodes + edges) into the in-memory rustworkx graph.
- `async def close(self) -> None` — Close the underlying aiosqlite connection.
- `def get_node(self, node_id: str) -> Optional[dict]` — Return the payload dict for a node by its ``node_id``.
- `def list_models(self) -> list[str]` — Return sorted list of canonical Odoo model names.
- `def children(self, node_id: str, *, symbol_type: Optional[str]=None) -> list[dict]` — Return CONTAINS children of a node, optionally filtered by symbol_type.
- `def who_extends(self, model_name: str, *, include_definers: bool=False) -> list[dict]` — Return classes whose EXTENDS (and optionally DEFINES) point to the model.
- `def find_model(self, model_name: str) -> Optional[dict]` — Aggregate view: canonical node + all contributors' fields + methods.
- `async def search_symbols(self, query: str, *, limit: int=20) -> list[dict]` — FTS5/BM25 lexical search over title + summary.
- `async def get_source(self, node_id: str) -> Optional[str]` — Resolve a symbol's source slice from disk (COLD), LRU-cached.
