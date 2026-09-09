---
id: F005
query_id: Q003
type: read
intent: Multi-store ranking is BM25 over candidate text
executed_at: 2026-09-09T23:24:11.921Z
parent_id: null
depth: 1
---

# F005 — Multi-store ranking is BM25 over candidate text

## Summary

MultiStoreSearchToolkit selects either origin.search or origin.fts_search per call, runs each with isolated timeouts, then reranks merged candidate content with BM25 and deduplicates by ID and content hash. SearchResult describes score as metric-native distance and exposes the same value as distance. OriginHit permits origin-native scores that cannot be compared across origins.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/toolkit.py`
  lines: 245-320,359-420
  symbol: `MultiStoreSearchToolkit / _run_origins / _rerank_with_bm25 / _deduplicate_hits`
  excerpt: |
    method = origin.fts_search if fts else origin.search

- path: `packages/ai-parrot/src/parrot/models/stores.py`
  lines: 23-43,46-103
  symbol: `StoreType / SearchOriginKind / SearchResult / OriginHit`
  excerpt: |
    def distance(self) -> float:
        return self.score

- path: `packages/ai-parrot/src/parrot/registry/routing/store_router.py`
  lines: 181-221
  symbol: `StoreRouter.execute`
  excerpt: |
    stores: dict[StoreType, "AbstractStore"],

## Notes

An explicit hybrid origin can preserve its native score in OriginHit without mislabeling RRF as a distance. Automatic router inclusion is additional scope because StoreType enumerates only pgvector/faiss/arango. IDs should distinguish collections while preserving deliberate cross-store identity.
