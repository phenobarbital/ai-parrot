---
type: Wiki Summary
title: parrot.knowledge.graphindex.sqlite_reader
id: mod:parrot.knowledge.graphindex.sqlite_reader
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: SQLiteGraphReader — read side of the SQLite GraphIndex artefact (FEAT-240).
relates_to:
- concept: class:parrot.knowledge.graphindex.sqlite_reader.SQLiteGraphReader
  rel: defines
---

# `parrot.knowledge.graphindex.sqlite_reader`

SQLiteGraphReader — read side of the SQLite GraphIndex artefact (FEAT-240).

HOT: graph topology loaded into an in-memory rustworkx ``PyDiGraph`` for
instant, deterministic navigation after a single ``await reader.load()``
call.  All HOT navigation methods (``list_models``, ``children``,
``who_extends``, ``find_model``) are synchronous and O(degree) once loaded.

COLD: source bodies resolved on demand from disk via line spans stamped in
``domain_tags``, bounded by a configurable LRU cache.  Lexical search runs
over FTS5/BM25 through the open ``aiosqlite`` connection.

No embeddings or semantic similarity are involved in this component.

## Classes

- **`SQLiteGraphReader`** — Read-only navigator over a per-tenant SQLite GraphIndex artefact.
