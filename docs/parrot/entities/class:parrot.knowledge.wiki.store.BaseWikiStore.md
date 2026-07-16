---
type: Wiki Entity
title: BaseWikiStore
id: class:parrot.knowledge.wiki.store.BaseWikiStore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Contract for wiki retrieval-plane backends.
---

# BaseWikiStore

Defined in [`parrot.knowledge.wiki.store`](../summaries/mod:parrot.knowledge.wiki.store.md).

```python
class BaseWikiStore(ABC)
```

Contract for wiki retrieval-plane backends.

Every consumer (``wiki/search.py``, ``wiki/ingest.py``,
``wiki/toolkit.py``, ``wiki/export.py``) talks only to this
surface, so backends are interchangeable via
:func:`create_wiki_store`:

- :class:`SQLiteWikiStore` — single-file ``wiki.db`` (FTS5/BM25).
- :class:`InMemoryWikiStore` — RAM indexes persisted as an OKF
  markdown bundle directory (``wiki/file_store.py``).

``search_fts`` is the lexical-search entry point on all backends
(the name predates the second backend; semantics are
backend-defined lexical ranking, not necessarily SQLite FTS).

## Methods

- `async def upsert_pages(self, pages: list[WikiPageRecord]) -> int`
- `async def add_edges(self, edges: list[tuple[str, str, str]]) -> int`
- `async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord], edges: Optional[list[tuple[str, str, str]]]=None) -> dict[str, Any]`
- `async def delete_page(self, concept_id: str) -> bool`
- `async def upsert_embedding(self, concept_id: str, vector: list[float], model: str='') -> None`
- `async def get_page(self, concept_id: str, include_body: bool=True) -> Optional[dict[str, Any]]`
- `async def list_pages(self, category: Optional[str]=None, limit: int=100) -> list[dict[str, Any]]`
- `async def search_fts(self, query: str, category: Optional[str]=None, limit: int=10) -> list[dict[str, Any]]`
- `async def search_vector(self, embedding: list[float], limit: int=10) -> list[dict[str, Any]]`
- `async def neighbors(self, concept_id: str, rel: Optional[str]=None, direction: str='both') -> list[dict[str, Any]]`
- `async def dump_pages(self) -> list[dict[str, Any]]`
- `async def dump_edges(self) -> list[dict[str, Any]]`
- `async def stats(self) -> dict[str, Any]`
- `async def orphan_sources(self) -> list[str]`
- `async def broken_edges(self) -> list[dict[str, Any]]`
- `async def missing_bodies(self) -> list[str]`
- `async def rebuild_from_tree(self, tree: dict[str, Any], content_loader: Optional[Callable[[str], Optional[str]]]=None, source_id: Optional[str]=None) -> dict[str, Any]` — Rebuild page rows from a PageIndex tree (derived-plane refresh).
