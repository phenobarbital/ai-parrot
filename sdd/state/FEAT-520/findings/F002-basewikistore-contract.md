# F002 — BaseWikiStore contract + SQLite port surface
**Query**: Q002/Q007 | **Confidence**: high

`packages/ai-parrot/src/parrot/knowledge/wiki/store.py`:
- `SCHEMA_VERSION = "2"` (:49), `WIKI_SCHEMA_SQL` (:53), `_MIGRATION_COLUMNS` (:166) — idempotent column migration pattern confirmed.
- `BaseWikiStore(ABC)` (:415) abstract methods: upsert_pages, add_edges, replace_source_slice, delete_page, upsert_embedding, get_page, list_pages, search_fts, search_vector, neighbors, dump_pages, dump_edges, stats, orphan_sources, broken_edges, missing_bodies. NON-abstract (deliberately, :572): upsert_symbols, symbols_for, find_symbols, search_symbols_fts, page_hashes — schema-v2 symbol surface (TASK-2747, landed ~2026-08) that Arango/InMemory may skip.
- SQLite backend uses **aiosqlite** (`_connect` :820, `executescript(WIKI_SCHEMA_SQL)` :886).
- Factory: `create_wiki_store(path, wiki_name=..., backend="sqlite"|"memory"|"arangodb")`.
- Arango backend: `wiki/arango_store.py` (search_fts :809).
