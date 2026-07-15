---
type: Wiki Summary
title: parrot.knowledge.graphindex.persist_sqlite
id: mod:parrot.knowledge.graphindex.persist_sqlite
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: SQLite persistence backend for GraphIndex (FEAT-240).
relates_to:
- concept: class:parrot.knowledge.graphindex.persist_sqlite.SQLitePersistence
  rel: defines
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
- concept: mod:parrot.knowledge.ontology.schema
  rel: references
---

# `parrot.knowledge.graphindex.persist_sqlite`

SQLite persistence backend for GraphIndex (FEAT-240).

Provides a per-tenant SQLite artefact as an alternative to ArangoDB.
Features WAL journal mode, a ``files`` table for incremental staleness
tracking, ``nodes``/``edges`` tables, and a ``nodes_fts`` FTS5/BM25
virtual table for lexical search.

Public API mirrors ``GraphIndexPersistence``:
- ``persist_graph(ctx, nodes, edges)`` — full persist with schema creation
- ``replace_document_slice(ctx, document_uri, nodes, edges)`` — atomic DELETE+INSERT
- ``is_stale(ctx, source_uri, mtime, sha1)`` — incremental staleness check

## Classes

- **`SQLitePersistence`** — Per-tenant SQLite persistence backend for GraphIndex.
