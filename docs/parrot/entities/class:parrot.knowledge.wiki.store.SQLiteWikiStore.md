---
type: Wiki Entity
title: SQLiteWikiStore
id: class:parrot.knowledge.wiki.store.SQLiteWikiStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Async single-file SQLite retrieval plane for one wiki.
relates_to:
- concept: class:parrot.knowledge.wiki.store.BaseWikiStore
  rel: extends
---

# SQLiteWikiStore

Defined in [`parrot.knowledge.wiki.store`](../summaries/mod:parrot.knowledge.wiki.store.md).

```python
class SQLiteWikiStore(BaseWikiStore)
```

Async single-file SQLite retrieval plane for one wiki.

Args:
    db_path: Path of the ``wiki.db`` file.  Parent directories are
        created automatically.
    wiki_name: Optional wiki name recorded in the ``meta`` table.

Example::

    store = WikiStore(storage_dir / "wiki.db", wiki_name="my-wiki")
    await store.upsert_pages([WikiPageRecord(concept_id="intro", ...)])
    hits = await store.search_fts("neural networks", limit=5)

## Methods

- `def db_path(self) -> Path` — Path of the underlying SQLite file.
- `async def upsert_pages(self, pages: list[WikiPageRecord]) -> int` — Insert or update wiki pages (and their FTS index rows).
- `async def add_edges(self, edges: list[tuple[str, str, str]]) -> int` — Insert typed edges.
- `async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord], edges: Optional[list[tuple[str, str, str]]]=None) -> dict[str, Any]` — Atomically replace all pages/edges derived from one source.
- `async def delete_page(self, concept_id: str) -> bool` — Delete a page and its FTS row, embeddings, and edges.
- `async def upsert_embedding(self, concept_id: str, vector: list[float], model: str='') -> None` — Store (or replace) the embedding vector for a page.
- `async def get_page(self, concept_id: str, include_body: bool=True) -> Optional[dict[str, Any]]` — Fetch a single page by ``concept_id`` (falls back to ``node_id``).
- `async def list_pages(self, category: Optional[str]=None, limit: int=100) -> list[dict[str, Any]]` — List page stubs (no bodies), optionally filtered by category.
- `async def search_fts(self, query: str, category: Optional[str]=None, limit: int=10) -> list[dict[str, Any]]` — BM25 lexical search over title/summary/body.
- `async def search_vector(self, embedding: list[float], limit: int=10) -> list[dict[str, Any]]` — Cosine-similarity search over stored page embeddings.
- `async def neighbors(self, concept_id: str, rel: Optional[str]=None, direction: str='both') -> list[dict[str, Any]]` — Return edge-adjacent pages/targets of a concept.
- `async def dump_pages(self) -> list[dict[str, Any]]` — Return every page row WITH bodies (bulk export path).
- `async def dump_edges(self) -> list[dict[str, Any]]` — Return every edge row (bulk export path).
- `async def stats(self) -> dict[str, Any]` — Aggregate counters for the wiki (single fast query set).
- `async def orphan_sources(self) -> list[str]` — Sources that produced no pages (zero rows in ``pages``).
- `async def broken_edges(self) -> list[dict[str, Any]]` — Edges whose destination is neither a page nor a source.
- `async def missing_bodies(self) -> list[str]` — Pages with an empty body (stub rows without content).
