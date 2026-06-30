---
id: F009
query_id: Q009
type: read
intent: Deep dive into GraphIndex write operations and sync protocol
executed_at: 2026-06-26T00:00:00Z
duration_ms: 4200
parent_id: F002
depth: 1
---

# F009 — GraphIndex Write Operations: Three-Layer Sync Model

## Summary

GraphIndex write operations maintain three synchronized layers: (1) rustworkx PyDiGraph with payload dicts, (2) in-memory maps (node_map, edge_index_map, node_id_list), (3) FAISS index for embeddings. Node IDs are deterministic SHA-1 hashes of (kind, title, summary). Key write methods: create_node/create_concept (lines 531-593), link_nodes (lines 595-647), merge_nodes (lines 764-869). The GraphIndexBuilder.ingest_document() method (lines 287-344) supports atomic per-document replacement via replace_document_slice(). Persistence supports both ArangoDB (per-kind vertex/edge collections) and SQLite (with FTS5 full-text search and staleness tracking via file hashes/mtimes).

## Citations

- path: `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py`
  lines: 531-593
  symbol: `_create_node`
  excerpt: |
    node_id = _mint_node_id(kind, title, summary)  # SHA-1 deterministic
    node = UniversalNode(node_id=node_id, kind=kind_enum, ...)
    self.assembler.add_node(node)
    await self.embedder.embed_nodes([node])

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py`
  lines: 387-429
  symbol: `is_stale`
  excerpt: |
    def is_stale(ctx, source_uri, mtime, sha1) -> bool:
        # Checks files table for matching source_uri, mtime, sha1

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py`
  lines: 287-344
  symbol: `ingest_document`

## Notes

For wiki→graph sync, the key insight is that GraphIndex already has atomic document replacement via ingest_document()/replace_document_slice(). When a wiki page is created/updated, we can use this mechanism to replace the corresponding graph nodes. The staleness tracking (mtime + SHA-1) in SQLite persistence is directly applicable to source collection change detection.
