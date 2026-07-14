---
type: Wiki Entity
title: InMemoryWikiStore
id: class:parrot.knowledge.wiki.file_store.InMemoryWikiStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: RAM-indexed wiki store persisted as an OKF markdown directory.
relates_to:
- concept: class:parrot.knowledge.wiki.store.BaseWikiStore
  rel: extends
---

# InMemoryWikiStore

Defined in [`parrot.knowledge.wiki.file_store`](../summaries/mod:parrot.knowledge.wiki.file_store.md).

```python
class InMemoryWikiStore(BaseWikiStore)
```

RAM-indexed wiki store persisted as an OKF markdown directory.

Args:
    bundle_dir: Root of the OKF bundle (typically
        ``{storage_dir}/pages`` — created automatically).
    wiki_name: Wiki name used in the bundle ``index.md`` header.

Example::

    store = InMemoryWikiStore(storage_dir / "pages", wiki_name="my-wiki")
    await store.upsert_pages([WikiPageRecord(concept_id="intro", ...)])
    hits = await store.search_fts("neural networks", limit=5)

## Methods

- `def bundle_dir(self) -> Path` — Root directory of the OKF bundle.
- `async def upsert_pages(self, pages: list[WikiPageRecord]) -> int` — Insert or update wiki pages (RAM indexes + bundle files).
- `async def add_edges(self, edges: list[tuple[str, str, str]]) -> int` — Insert typed edges and re-persist affected source pages.
- `async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord], edges: Optional[list[tuple[str, str, str]]]=None) -> dict[str, Any]` — Atomically replace all pages/edges derived from one source.
- `async def delete_page(self, concept_id: str) -> bool` — Delete a page: RAM indexes, edges, embedding, bundle file.
- `async def upsert_embedding(self, concept_id: str, vector: list[float], model: str='') -> None` — Store (or replace) the embedding vector for a page.
- `async def get_page(self, concept_id: str, include_body: bool=True) -> Optional[dict[str, Any]]` — Fetch a page by ``concept_id`` (falls back to ``node_id``).
- `async def list_pages(self, category: Optional[str]=None, limit: int=100) -> list[dict[str, Any]]` — List page stubs, optionally filtered by category.
- `async def search_fts(self, query: str, category: Optional[str]=None, limit: int=10) -> list[dict[str, Any]]` — TF-IDF lexical search over title/summary/body postings.
- `async def search_vector(self, embedding: list[float], limit: int=10) -> list[dict[str, Any]]` — Cosine-similarity search over the embeddings map.
- `async def neighbors(self, concept_id: str, rel: Optional[str]=None, direction: str='both') -> list[dict[str, Any]]` — Return edge-adjacent pages/targets of a concept.
- `async def dump_pages(self) -> list[dict[str, Any]]` — Return every page row WITH bodies (bulk export path).
- `async def dump_edges(self) -> list[dict[str, Any]]` — Return every edge row (bulk export path).
- `async def stats(self) -> dict[str, Any]` — Aggregate counters for the wiki.
- `async def orphan_sources(self) -> list[str]` — Sources (from the JSON manifest) that produced no pages.
- `async def broken_edges(self) -> list[dict[str, Any]]` — Edges whose destination is neither a page nor a source.
- `async def missing_bodies(self) -> list[str]` — Pages with an empty body.
