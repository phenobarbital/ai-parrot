---
id: F003
query_id: Q006,Q007
type: read
intent: Confirm BaseWikiStore contract and create_wiki_store factory
executed_at: 2026-08-23T02:20:00Z
depth: 0
---
# F003 — BaseWikiStore is the single contract every consumer uses; factory builds 3 backends

## Summary
`BaseWikiStore(ABC)` (store.py:289-385): write = `upsert_pages`, `add_edges`,
`replace_source_slice`, `delete_page`, `upsert_embedding`; read = `get_page`, `list_pages`,
`search_fts`, `search_vector`, `neighbors`, `dump_pages`, `dump_edges`, `stats`; lint =
`orphan_sources`, `broken_edges`, `missing_bodies`, `rebuild_from_tree`. Docstring: "Every
consumer (search.py, ingest.py, toolkit.py, export.py) talks only to this surface". 
`create_wiki_store(storage_dir, wiki_name, backend, **kwargs)` (1217-1274) returns
`SQLiteWikiStore` / `InMemoryWikiStore` / `ArangoDBWikiStore`; unknown backend raises.
A federated implementation of this ABC is a drop-in for every consumer.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 289-385
  symbol: `BaseWikiStore`
  excerpt: |
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict]
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict]
    async def neighbors(self, concept_id: str, rel: Optional[str] = None, direction: str = "both") -> list[dict]
    async def stats(self) -> dict[str, Any]
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 1217-1274
  symbol: `create_wiki_store`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 997-1043
  symbol: `SQLiteWikiStore.search_fts`
  excerpt: |
    SELECT p.concept_id, p.node_id, p.title, p.category, p.summary,
           p.source_id, p.token_count, -bm25(pages_fts) AS score
    -- scores are -bm25 and NOT normalised — callers normalise
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
  lines: 78-108
  symbol: `pages`, `edges`, `pages_fts` DDL
  excerpt: |
    concept_id  TEXT PRIMARY KEY,   -- pages
    PRIMARY KEY (src, dst, rel)     -- edges
