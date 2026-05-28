---
id: F007
query_id: Q011
type: read
intent: Read the parrot.stores public surface to confirm dispatch idiom.
executed_at: 2026-05-28T00:00:00Z
duration_ms: 30
parent_id: null
depth: 0
---

# F007 — `parrot.stores.__init__` mirrors the embeddings dispatch pattern

## Summary

`parrot.stores.__init__` is tiny (10 lines): it re-exports `AbstractStore`
from `.abstract` and declares `supported_stores`, a dict mapping the
backend key to its concrete class name — exactly the same dispatch
idiom as `parrot.embeddings.__init__`'s `supported_embeddings`. There
is no `Registry` class for stores (unlike embeddings); the dispatch
happens elsewhere (see F009).

## Citations

- path: `packages/ai-parrot/src/parrot/stores/__init__.py`
  lines: 1-10
  symbol: `supported_stores`
  excerpt: |
    from .abstract import AbstractStore
    # from .postgres import PgVectorStore
    supported_stores = {
        'postgres': 'PgVectorStore',
        'milvus': 'MilvusStore',
        'kb': 'KnowledgeBaseStore',
        'faiss_store': 'FaissStore',
        'arango': 'ArangoStore',
        'bigquery': 'BigQueryStore',
    }

## Notes

- `parrot.stores.__init__` **MUST stay in core** for the same reason as
  embeddings: it owns the dispatch table.
- The commented-out `from .postgres import PgVectorStore` (line 2)
  signals an earlier eager-import that was rolled back — confirms
  awareness that backend deps must be deferred.
- The `supported_stores` keys (postgres / milvus / kb / faiss_store /
  arango / bigquery) map almost 1:1 to the proposed extras of the new
  package, except `kb` (KnowledgeBaseStore — likely STAYS in core as a
  higher-level abstraction).
