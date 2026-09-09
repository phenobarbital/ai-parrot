---
id: F008
query_id: Q004
type: read
intent: Official documentation supports embedded async vector and FTS search
executed_at: 2026-09-09T23:24:11.921Z
parent_id: null
depth: 1
---

# F008 — Official documentation supports embedded async vector and FTS search

## Summary

LanceDB OSS connects to a local directory. Python exposes connect_async, AsyncConnection and AsyncTable. Async FTS index creation uses create_index with FTS configuration; create_fts_index is a synchronous API. Current documentation describes Lance-native FTS and rejects legacy use_tantivy options. Hybrid retrieval combines vector and lexical candidates with default RRF and supports explicit vector/text inputs.

## Citations

External documentation; URLs and supported claims below.

## Notes

External sources, accessed 2026-09-10:
- https://docs.lancedb.com/quickstart — local directory deployment.
- https://lancedb.github.io/lancedb/python/python/ — async connection/table, Arrow schema and read consistency.
- https://docs.lancedb.com/indexing/fts-index — async create_index/FTS and current native implementation.
- https://docs.lancedb.com/search/hybrid-search — vector/text hybrid with RRF.
- https://docs.lancedb.com/search/full-text-search — BM25 and FTS index prerequisite.
These are current documentation capabilities, not proof for a selected release. No SDK version was pinned or runtime-tested.
