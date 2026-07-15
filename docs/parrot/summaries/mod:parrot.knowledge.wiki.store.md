---
type: Wiki Summary
title: parrot.knowledge.wiki.store
id: mod:parrot.knowledge.wiki.store
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: WikiStore — single-file SQLite retrieval plane for the LLM Wiki.
relates_to:
- concept: class:parrot.knowledge.wiki.store.BaseWikiStore
  rel: defines
- concept: class:parrot.knowledge.wiki.store.SQLiteWikiStore
  rel: defines
- concept: class:parrot.knowledge.wiki.store.WikiPageRecord
  rel: defines
- concept: func:parrot.knowledge.wiki.store.create_wiki_store
  rel: defines
- concept: func:parrot.knowledge.wiki.store.estimate_tokens
  rel: defines
- concept: func:parrot.knowledge.wiki.store.rank_by_cosine
  rel: defines
- concept: mod:parrot.knowledge.pageindex.utils
  rel: references
- concept: mod:parrot.knowledge.wiki.file_store
  rel: references
---

# `parrot.knowledge.wiki.store`

WikiStore — single-file SQLite retrieval plane for the LLM Wiki.

Machine-first knowledge storage (follow-up to FEAT-260): every wiki
query is answered from indexed SQL — no YAML/markdown parsing, no tree
walks, and no dual-toolkit fan-out at retrieval time.

Design (mirrors ``graphindex/persist_sqlite.py`` patterns):

- One ``wiki.db`` per wiki (WAL journal mode, ``aiosqlite``).
- ``pages`` — page bodies live IN the database, keyed by stable
  ``concept_id`` (volatile PageIndex ``node_id`` kept as a secondary
  column).  ``category`` and edge ``rel`` are open strings — no enum
  ceremony in the machine plane.
- ``edges`` — typed relations (``summarizes``, ``references``, …).
- ``sources`` — absorbs the former ``.manifest.json`` manifest
  (SHA-1 + mtime staleness detection).
- ``pages_fts`` — FTS5/BM25 lexical index over title/summary/body.
- ``embeddings`` — optional per-page vectors for cosine re-ranking.
- ``meta`` — schema version + wiki name.

The store is a *derived* retrieval plane: PageIndex remains the
authoring/structuring engine, and the database can always be rebuilt
from a PageIndex tree via :meth:`WikiStore.rebuild_from_tree`.

## Classes

- **`WikiPageRecord(BaseModel)`** — A single wiki page row in the retrieval plane.
- **`BaseWikiStore(ABC)`** — Contract for wiki retrieval-plane backends.
- **`SQLiteWikiStore(BaseWikiStore)`** — Async single-file SQLite retrieval plane for one wiki.

## Functions

- `def estimate_tokens(text: str) -> int` — Cheap deterministic token estimate for budget accounting.
- `def rank_by_cosine(embedding: list[float], candidates: list[tuple[dict[str, Any], list[float]]], limit: int=10) -> list[dict[str, Any]]` — Rank candidate stubs by cosine similarity to a query vector.
- `def create_wiki_store(storage_dir: str | Path, wiki_name: str='', backend: str='sqlite') -> BaseWikiStore` — Instantiate the configured wiki retrieval-plane backend.
