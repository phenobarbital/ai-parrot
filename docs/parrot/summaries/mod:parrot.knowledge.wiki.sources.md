---
type: Wiki Summary
title: parrot.knowledge.wiki.sources
id: mod:parrot.knowledge.wiki.sources
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Source collection manager for the LLM Wiki feature (FEAT-260).
relates_to:
- concept: class:parrot.knowledge.wiki.sources.SourceCollectionManager
  rel: defines
- concept: mod:parrot.knowledge.wiki.models
  rel: references
- concept: mod:parrot.knowledge.wiki.store
  rel: references
---

# `parrot.knowledge.wiki.sources`

Source collection manager for the LLM Wiki feature (FEAT-260).

Implements the "Raw Sources" layer of Karpathy's 3-layer architecture.
Tracks ingested source documents in one of two backends, matching the
wiki's ``storage_backend``:

- ``"sqlite"`` (default) — the ``sources`` table of the wiki's
  single-file SQLite retrieval plane (``wiki.db`` — see
  :mod:`parrot.knowledge.wiki.store`).  A legacy ``.manifest.json``
  found on first open is migrated into the database automatically and
  renamed to ``.manifest.json.bak``.
- ``"json"`` — a plain ``.manifest.json`` file in ``sources_dir``
  (atomic tmp-file writes), used with the SQLite-free
  ``InMemoryWikiStore`` backend.

Staleness detection reuses the same mtime + SHA-1 pattern as
``SQLitePersistence.is_stale()`` in ``graphindex/persist_sqlite.py``.

The public API is synchronous (callers off-load to a thread pool via
``asyncio.to_thread``); the sqlite mode uses short-lived per-call
``sqlite3`` connections — WAL mode makes this safe alongside the async
:class:`~parrot.knowledge.wiki.store.WikiStore` connections on the same
file.

## Classes

- **`SourceCollectionManager`** — Manages the raw-source collection for a single wiki instance.
