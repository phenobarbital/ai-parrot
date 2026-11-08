---
id: F028
query_id: Q208
type: wiki_query
intent: "Bookstore index storage"
executed_at: 2026-11-06T13:29:04Z
duration_ms: 3000
parent_id: null
depth: 1
merged_from: [FW-008]
---

# F028 — Bookstore does not use ArangoDB: the catalog is a sync SQLite + FTS5 `library.db` (`CatalogStore`), book content lives in PageIndex trees on disk, and a wikitoolkit export projects the book graph

## Summary

`parrot/knowledge/bookstore/` is "a personal indexed library of books over PageIndex". `catalog.py` holds `CatalogStore`, "Card catalog over one `library.db` file" — SQLite + FTS5 for cards, relations, judgements and communities. `library.py` (`Bookstore`) composes one catalog + PageIndex trees per scope (project + global). `wiki_export.py` projects the book graph into a wikitoolkit plane. The FEAT-670 spec's plane inventory states the same: BookStore catalog = `CatalogStore` (sync `sqlite3`, `books_fts`); PageIndex = `JSONTreeStore` + `NodeContentStore` (.md) + `.npy` embeddings — "not SQLite". So moving Bookstore to SurrealDB is **not** part of removing ArangoDB; it is an optional consolidation, and the draft's "documents no-OKF reutilizan document/section/chunk" model is not how Bookstore is stored today (tree nodes, not chunks).

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py`
  lines: 163-738
  symbol: `CatalogStore`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py#CatalogStore
  score: 1.00 (symbols lookup)
  excerpt: |
    class CatalogStore — "Card catalog over one ``library.db`` file."
    __init__(self, db_path: Path | str) -> None            # L171-177
    upsert  L300-339: Insert or replace one card (and its FTS row) atomically.
    upsert_relations  L496-524: Insert or replace edges, canonicalising symmetric pairs.
    upsert_communities  L680-713: Replace the entire partition with ``communities``.

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py`
  lines: 228-250
  symbol: `Bookstore._catalog`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/knowledge/bookstore/library.py#Bookstore._catalog
  excerpt: |
    Bookstore._catalog(self, scope: str) -> CatalogStore            # L228-231
    Bookstore._stores(self) -> list[tuple[str, CatalogStore]]       # L249-250

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py`
  lines: 29-223
  symbol: `BookstoreToolkit`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/knowledge/bookstore/toolkit.py#BookstoreToolkit
  score: 1.00
  excerpt: |
    class BookstoreToolkit(AbstractToolkit):
        """Read-only tools over a :class:`~parrot.knowledge.bookstore.library.Bookstore`."""
        async def catalog_search(self, query: str, top_k: int = 8) -> list[dict[str, Any]]:
            """... Lexical (FTS/BM25) search over the per-book catalog cards ..."""
            cards = self._bookstore.catalog_search(query, top_k=max(1, min(top_k, 50)))

- path: `packages/ai-parrot/src/parrot/knowledge/bookstore/`
  symbol: `directory overview (12 entries)`
  wiki_page_id: dir:packages/ai-parrot/src/parrot/knowledge/bookstore
  excerpt: |
    catalog.py — SQLite + FTS5 catalog store for Bookstore cards.
    library.py — The Bookstore manager — catalogs + PageIndex trees per scope.
    relations.py — Deterministic (LLM-free) relation computation for the book graph.
    wiki_export.py — ``bookstore export-wiki`` — project the book graph into a wikitoolkit plane.
    config.py — Library directory resolution for the Bookstore.

- path: `sdd/specs/helixdb-provider.spec.md`
  symbol: `§1 Problem Statement (plane inventory)`
  wiki_page_id: file:sdd/specs/helixdb-provider.spec.md
  excerpt: |
    | BookStore catalog | `CatalogStore` (sync `sqlite3`, `books_fts`) | cards + relations + judgements + communities |
    | PageIndex | `JSONTreeStore` + `NodeContentStore` (.md) + `NodeEmbeddingStore` (.npy) — **not SQLite** | tree + bodies + embedding matrix; hybrid search = `bm25s` + numpy + LLM walk |

## Notes

- `CatalogStore` is **synchronous** `sqlite3`; a server-backed Bookstore store is a new async surface, not a drop-in.
- FEAT-670 decided "PageIndex and BookStore **projections**: files / SQLite stay canonical" and listed "Full relocation of PageIndex / BookStore" as a non-goal. The draft's KnowledgeStore making SurrealDB the Bookstore store ("Sustituye a … Bookstore") contradicts that prior decision; the proposal should either adopt projection-only or justify relocation.
- No ArangoDB reference surfaced anywhere in the Bookstore pages.
- [cross-lane: type=grep, intent=confirm zero arango/postgres references under packages/ai-parrot/src/parrot/knowledge/bookstore and knowledge/pageindex stores]
