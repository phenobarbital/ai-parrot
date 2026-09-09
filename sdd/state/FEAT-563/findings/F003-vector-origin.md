---
id: F003
query_id: Q003
type: read
intent: Vector and lexical federation already have an adapter
executed_at: 2026-09-09T23:24:11.921Z
parent_id: null
depth: 1
---

# F003 — Vector and lexical federation already have an adapter

## Summary

VectorStoreOrigin awaits similarity_search(query, limit=k), and detects FTS through a callable fulltext_search attribute. Its fts_search awaits fulltext_search(query, limit=k). Normalization retains native order, IDs, content, metadata and score.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py`
  lines: 16-105
  symbol: `VectorStoreOrigin`
  excerpt: |
    self.supports_fts = callable(getattr(store, "fulltext_search", None))

- path: `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/base.py`
  lines: 18-72
  symbol: `SearchOrigin`
  excerpt: |
    async def search(self, query: str, k: int) -> List[OriginHit]:

## Notes

An FTS-disabled store still advertises FTS if its method exists. Prefer making FTS mandatory for this backend's first release, or explicitly design capability handling. A single toolkit store_search calls the vector adapter's search only; it does not also call its FTS method.
