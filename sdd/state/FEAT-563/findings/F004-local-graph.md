---
id: F004
query_id: Q003
type: read
intent: Local graph retrieval exists, but graph seeding is separate
executed_at: 2026-09-09T23:24:11.921Z
parent_id: null
depth: 1
---

# F004 — Local graph retrieval exists, but graph seeding is separate

## Summary

GraphIndexOrigin combines GraphExpandedRetriever with an optional SQLiteGraphReader for FTS. The retriever takes an in-memory rustworkx graph and nodes plus either a GraphIndexEmbedder (FAISS seed path) or HybridPageIndexSearch. SQLiteGraphReader is local topology and lexical lookup, with no semantic embeddings of its own.

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/graphindex.py`
  lines: 23-83,109-159
  symbol: `GraphIndexOrigin`
  excerpt: |
    self.supports_fts = reader is not None

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py`
  lines: 168-211,218-242
  symbol: `GraphExpandedRetriever`
  excerpt: |
    if embedder is None and hybrid_search is None:

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/sqlite_reader.py`
  lines: 1-12,47-57,75-85,320-358
  symbol: `SQLiteGraphReader / search_symbols`
  excerpt: |
    import aiosqlite

## Notes

Do not describe LanceDB as a graph database or claim it automatically replaces GraphIndex's FAISS seed index. Federation with prebuilt local graph artifacts is plausible; exact construction and offline ingestion must be proven in a later integration fixture.
