---
id: FC-011
query_id: Q011
type: tree
intent: "How does Bookstore persist its catalog/index today?"
executed_at: 2026-11-06T13:44:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-011 — Bookstore never touches ArangoDB: SQLite + FTS5 catalog (`library.db`) and PageIndex JSON trees per scope

## Summary

`parrot/knowledge/bookstore/` (12 files, 5194 lines) stores everything on local disk under `<scope>/.parrot/library/`: `library.db` (synchronous `sqlite3`, `books` table + `books_fts`) for the catalog of per-book cards, and `trees/` for PageIndex hierarchical trees (`<slug>.json` + markdown sidecars). There is no chunk/embedding table and no graph database; relations between books live in `relations.py` and the optional wiki export writes a **SQLite** wiki plane (`backend="sqlite"`). `grep -rnE "sqlite|aiosqlite|arango|asyncpg|postgres|..."` over the package returns no `arango`, `asyncpg` or `postgres` hit. Moving Bookstore to a SurrealDB `document/section/chunk` model (draft §5.2) is therefore **not part of removing ArangoDB** — it is a separate re-platforming of a working, Arango-free subsystem, and it would replace PageIndex tree retrieval with chunk retrieval.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/__init__.py`
  lines: 1-20
  symbol: package docstring
  excerpt: |
    """Bookstore — a personal indexed library of books over PageIndex.
    Books (PDF / EPUB / Markdown / plain text) are indexed as PageIndex
    hierarchical trees (chapters / sections / page ranges) and catalogued
    with a per-book "ficha" (:class:`BookCard`) stored in a SQLite + FTS5 catalog
    Data lives per scope under ``<scope>/.parrot/library/``:
    - ``library.db`` — the catalog (``books`` table + ``books_fts``).
    - ``trees/`` — the PageIndexToolkit storage dir (``<slug>.json`` lean trees + ``<slug>/*.md`` sidecars).

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py`
  lines: 3-13
  symbol: module docstring
  excerpt: |
    3:One ``library.db`` per library location holds the ``books`` table (the
    9:- Synchronous ``sqlite3`` with short-lived per-call connections, WAL
    13:  and the Click CLI stays wrapper-free. Switching to ``aiosqlite``

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/config.py`
  lines: 26-51
  symbol: `DB_FILENAME`
  excerpt: |
    26:DB_FILENAME = "library.db"
    46:        """Path of the catalog database (``library.db``)."""
    51:        """PageIndex ``storage_dir`` for this location (``trees/``)."""

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/wiki_export.py`
  lines: 11-278
  symbol: wiki export
  excerpt: |
    11:Idempotency note: ``BaseWikiStore`` has no delete-edges API, so a
    155:    db_path = out_dir / "wiki.db"
    248:            backend="sqlite",
    278:        backend="sqlite",

## Notes

- File sizes: `library.py` 1450, `catalog.py` 839, `relations.py` 693, `cli.py` 615, `models.py` 377, `wiki_export.py` 281, `carding.py` 253, `toolkit.py` 223, `mcp_server.py` 146, `config.py` 130, `_llm.py` 105, `__init__.py` 82.
- Bookstore is multi-process-safe today only as far as SQLite WAL allows; the draft's motivation ("no embedded engine admits several writer processes") applies to it in principle, but it is single-user/local by design ("personal indexed library").
- `wiki_export.py:11` records a real `BaseWikiStore` gap (no delete-edges API) that any new backend inherits.
