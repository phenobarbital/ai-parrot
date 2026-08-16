---
id: F001
slug: basewikistore-contract
query: "BaseWikiStore abstract interface and SQLite schema"
type: read
---

# F001: BaseWikiStore Contract

## Key Facts

- `BaseWikiStore` (store.py:279) defines 15 abstract methods + 1 concrete (`rebuild_from_tree`)
- Write: `upsert_pages`, `add_edges`, `replace_source_slice`, `delete_page`, `upsert_embedding`
- Read: `get_page`, `list_pages`, `search_fts`, `search_vector`, `neighbors`, `dump_pages`, `dump_edges`, `stats`
- Lint: `orphan_sources`, `broken_edges`, `missing_bodies`
- `WikiPageRecord` (store.py:205): Pydantic model with concept_id (PK), node_id, title, category, summary, body, source_id, token_count, origin, asserted_by
- `create_wiki_store()` (store.py:1197): factory with `backend` param, returns `BaseWikiStore`
- `rank_by_cosine()` (store.py:236): shared brute-force cosine helper, reusable by any backend
- `WikiStore = SQLiteWikiStore` (store.py:1194): backwards-compat alias

## SQLite Schema (WIKI_SCHEMA_SQL, store.py:50-105)

- `meta`: key/value pairs
- `sources`: source_id PK, source_uri UNIQUE, file_hash, mtime, ingested_at, pages_generated (JSON text), status
- `pages`: concept_id PK, node_id, title, category, summary, body, source_id, token_count, created_at, updated_at, origin, asserted_by
- `edges`: (src, dst, rel) composite PK, provenance
- `pages_fts`: FTS5 on (title, summary, body), tokenize='unicode61'
- `embeddings`: concept_id PK, vector BLOB (float32), model

## FTS5 Configuration

- Tokenizer: unicode61
- Indexed columns: title, summary, body
- Ranking: BM25 via `bm25(pages_fts)` (negated for ordering)
