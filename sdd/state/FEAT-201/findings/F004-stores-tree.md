---
id: F004
query_id: Q004
type: tree
intent: Enumerate the parrot.stores module tree.
executed_at: 2026-05-28T00:00:00Z
duration_ms: 30
parent_id: null
depth: 0
---

# F004 — `parrot/stores/` tree: 6 vector-store backends + KB / parents / utils

## Summary

The stores subsystem is the largest of the three (28 Python files). It
contains 6 concrete vector-store backends plus three sub-packages:
`kb/` (knowledge-base abstraction), `parents/` (parent-child retrieval),
and `utils/` (chunking + contextual augmentation). The base / shared
types are in `abstract.py` and `models.py`.

## Citations

- path: `packages/ai-parrot/src/parrot/stores/`
  lines: null
  symbol: tree
  excerpt: |
    stores/
    ├── __init__.py          ← supported_stores map (STAYS in core)
    ├── abstract.py          ← AbstractStore (STAYS in core)
    ├── models.py            ← Document, SearchResult, StoreConfig, DistanceStrategy (STAYS — shared types)
    ├── empty.py             ← EmptyStore (no backend) (STAYS — utility)
    ├── cache.py             ← cache helpers (TBD — likely STAYS)
    ├── arango.py            ← ArangoDBStore (MOVES → [arango])
    ├── bigquery.py          ← BigQueryStore (MOVES → [bigquery])
    ├── faiss_store.py       ← FAISSStore (MOVES → [faiss])
    ├── milvus.py            ← MilvusStore (MOVES → [milvus])
    ├── pgvector.py          ← (small wrapper) (MOVES → [pgvector])
    ├── postgres.py          ← PgVectorStore (the real pgvector impl) (MOVES → [pgvector])
    ├── kb/                  ← knowledge-base sub-package (8 files: abstract, cache, doc, hierarchy, local, prompt, redis, store, user)
    ├── parents/             ← parent-child retrieval (4 files: abstract, factory, in_table)
    └── utils/               ← chunking + contextual augmentation (chunking.py, contextual.py)

- path: `packages/ai-parrot/src/parrot/stores/postgres.py`
  lines: 49
  symbol: `PgVectorStore`
  excerpt: |
    class PgVectorStore(AbstractStore):

- path: `packages/ai-parrot/src/parrot/stores/milvus.py`
  lines: 67
  symbol: `MilvusStore`
  excerpt: |
    class MilvusStore(AbstractStore):

- path: `packages/ai-parrot/src/parrot/stores/arango.py`
  lines: 28
  symbol: `ArangoDBStore`
  excerpt: |
    class ArangoDBStore(AbstractStore):

- path: `packages/ai-parrot/src/parrot/stores/bigquery.py`
  lines: 23
  symbol: `BigQueryStore`
  excerpt: |
    class BigQueryStore(AbstractStore):

## Notes

- **Sub-packages `kb/`, `parents/`, `utils/` are likely STAY-in-core
  candidates** because they import `parrot.stores.abstract.AbstractStore`
  and `parrot.stores.models.Document/SearchResult` extensively but are
  themselves higher-level orchestration code (not backend-specific). The
  proposal should treat the move-boundary as the 6 backend files in the
  top-level, not the whole `stores/` tree. The spec phase can revisit.
- `pgvector.py` exists alongside `postgres.py`. `postgres.py` contains
  the real `PgVectorStore` class (line 49); `pgvector.py` is probably a
  thin wrapper. Worth confirming in the spec phase.
