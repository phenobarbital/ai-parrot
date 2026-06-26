---
id: F004
query_id: Q004
type: read
intent: Survey vector stores and search capabilities
executed_at: 2026-06-26T00:00:00Z
duration_ms: 2000
parent_id: null
depth: 0
---

# F004 — Vector Stores: 6 Backends with Hybrid/MMR/ColBERT Search

## Summary

The stores package provides `AbstractStore` with 6 backends: PgVectorStore (primary, with hybrid BM25+vector, MMR, ColBERT), ArangoDBStore (graph-native with hybrid search), MilvusStore, FAISSStore (in-memory with S3 persistence), BigQueryStore, and KnowledgeBaseStore (in-memory FAISS). Search capabilities include similarity search, hybrid search, MMR search, ColBERT search, metadata filtering, and parent document retrieval. The KB sub-package provides AbstractKnowledgeBase with activation patterns, RedisKnowledgeBase, LocalKB, UserContext, DocumentMetadata, and EmployeeHierarchyKB.

## Citations

- path: `packages/ai-parrot/src/parrot/stores/abstract.py`
  lines: 75-511
  symbol: `AbstractStore`

- path: `packages/ai-parrot/src/parrot/stores/kb/abstract.py`
  lines: 1-68
  symbol: `AbstractKnowledgeBase`

- path: `packages/ai-parrot/src/parrot/stores/__init__.py`
  lines: 6-13
  excerpt: |
    supported_stores = {
        'postgres': 'PgVectorStore',
        'milvus': 'MilvusStore',
        'kb': 'KnowledgeBaseStore',
        'faiss_store': 'FaissStore',
        'arango': 'ArangoStore',
        'bigquery': 'BigQueryStore',
    }

## Notes

For the wiki, the combined search layer needs to unify PageIndex tree search + GraphIndex graph-expanded search + optional vector store similarity search. The existing `HybridPageIndexSearch` already combines BM25 + LLM walk; the `GraphExpandedRetriever` adds graph expansion. A wiki-level unified search would orchestrate both and merge/rerank results.
