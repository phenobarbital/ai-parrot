"""BookstoreToolkit — the read-only agent surface of the library.

Every public async method auto-becomes a ``bookstore_*`` tool via
:class:`~parrot.tools.toolkit.AbstractToolkit`. The surface is
deliberately small and funnel-shaped for research:

1. ``bookstore_catalog_search`` — which book covers X? (cheap, no LLM)
1b. ``bookstore_related_books`` / ``bookstore_communities`` — expand by
    the book graph before opening anything (FEAT-533)
2. ``bookstore_get_toc`` — orient inside the chosen book
3. ``bookstore_search_book`` — targeted in-book hybrid search
4. ``bookstore_read_section`` — read only the sections that matter

Ingestion/removal is NOT exposed here — managing the library is the
``bookstore`` CLI's job (indexing a book is a minutes-long LLM batch,
the wrong shape for a stdio tool call, same reasoning that keeps
``bookstore relate``/``export-wiki`` CLI-only).
"""

from __future__ import annotations

from typing import Any, Optional

from parrot.tools.toolkit import AbstractToolkit

from .library import Bookstore


class BookstoreToolkit(AbstractToolkit):
    """Read-only tools over a :class:`~parrot.knowledge.bookstore.library.Bookstore`.

    Args:
        bookstore: The composed library manager (catalogs + trees).
    """

    name = "bookstore"
    tool_prefix = "bookstore"

    def __init__(self, bookstore: Bookstore, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._bookstore = bookstore

    async def catalog_search(self, query: str, top_k: int = 8) -> list[dict[str, Any]]:
        """Find which books cover a topic — ALWAYS start here.

        Lexical (FTS/BM25) search over the per-book catalog cards
        (title, authors, topics, summary, table of contents). Cheap —
        no LLM involved. Use the returned ``book_id`` values with
        ``bookstore_get_toc`` / ``bookstore_search_book``.

        Args:
            query: Topic or keywords to research (e.g. "index tuning").
            top_k: Maximum books returned (clamped to 1-50).

        Returns:
            Compact card dicts, best match first.
        """
        cards = self._bookstore.catalog_search(query, top_k=max(1, min(top_k, 50)))
        return [card.brief() for card in cards]

    async def list_books(self) -> list[dict[str, Any]]:
        """List every book in the library (project + global scopes).

        Returns:
            Compact card dicts, project scope winning id collisions.
        """
        return [card.brief() for card in self._bookstore.list_books()]

    async def get_card(self, book_id: str) -> dict[str, Any]:
        """Full catalog card (ficha) for one book.

        Includes the rendered table-of-contents digest — useful to
        decide whether the book is worth opening.

        Args:
            book_id: Id from ``bookstore_catalog_search`` /
                ``bookstore_list_books``.
        """
        card = self._bookstore.get_card(book_id)
        data = card.model_dump(mode="json")
        data.pop("toc", None)  # the digest is the readable form
        data.pop("source_sha256", None)
        return data

    async def get_toc(self, book_id: str) -> dict[str, Any]:
        """Structured table of contents with node ids and page ranges.

        Each entry's ``node_id`` is the key for
        ``bookstore_read_section``.

        Args:
            book_id: The book to open.
        """
        return self._bookstore.get_toc(book_id)

    async def search_book(self, book_id: str, query: str, top_k: int = 8) -> list[dict[str, Any]]:
        """Search inside ONE book's chapter tree.

        Hybrid BM25 + LLM tree-walk when a model is configured,
        BM25-only otherwise. Prefer this over reading sections blindly.

        Args:
            book_id: The book to search.
            query: Natural-language question or keywords.
            top_k: Maximum sections returned (clamped to 1-50).

        Returns:
            ``{node_id, title, summary, score, source}`` candidates.
        """
        return await self._bookstore.search_book(book_id, query, top_k=max(1, min(top_k, 50)))

    async def read_section(self, book_id: str, node_id: str) -> dict[str, Any]:
        """Read one section's full markdown content.

        Cite results as: *book title*, section title, pp. start-end.

        Args:
            book_id: The book.
            node_id: Section id from ``bookstore_get_toc`` or
                ``bookstore_search_book``.
        """
        return self._bookstore.read_section(book_id, node_id)

    async def related_books(
        self,
        book_id: str,
        rel: Optional[str] = None,
        depth: int = 1,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Books related to ``book_id`` through the library graph.

        Use this right after ``bookstore_catalog_search`` on its best
        hit, before opening any book — it surfaces the author's other
        works, sibling works of the same tradition/era, or conceptually
        adjacent works an agent would otherwise only find by luck.
        SQL-only, no LLM call, no matter what.

        Each item carries ``rel`` (``same_author``, ``shares_topic``,
        ``same_tradition``, ``same_genre``, ``same_era``,
        ``same_language``, ``influenced_by``, ``responds_to``,
        ``parallels``, ``contrasts_with``, ``same_community``),
        ``origin`` (``deterministic`` | ``llm`` | ``community``) and,
        for LLM relations, ``confidence`` and a ``rationale``. **Cite
        the origin** when a relation drives a claim — e.g. "the library
        links these as parallels (LLM-inferred, 0.7)" vs "same author
        (deterministic)".

        Args:
            book_id: Origin book id.
            rel: Restrict to one relation kind.
            depth: Hops to walk from ``book_id`` (clamped to 1-2).
            top_k: Maximum results returned (clamped to 1-50).
        """
        return self._bookstore.related_books(
            book_id,
            rel=rel,
            depth=max(1, min(depth, 2)),
            top_k=max(1, min(top_k, 50)),
        )

    async def communities(self) -> list[dict[str, Any]]:
        """List every detected community (thematic/author/tradition cluster).

        Use when a question is thematic or comparative ("what schools
        of thought does this library cover?") rather than about one
        book. Members here are compact briefs (``book_id``, ``title``)
        — use ``bookstore_get_community`` for the full row including
        inter-community relations. Run `bookstore relate --all`
        (CLI-only) first if this returns nothing.
        """
        cards_by_id = {card.book_id: card for card in self._bookstore.list_books()}
        result: list[dict[str, Any]] = []
        for community in self._bookstore.communities():
            data = community.model_dump(mode="json")
            data.pop("inter_relations", None)
            member_ids = data.pop("member_book_ids", [])
            data["members"] = [
                {"book_id": member_id, "title": cards_by_id[member_id].title}
                for member_id in member_ids
                if member_id in cards_by_id
            ]
            result.append(data)
        return result

    async def get_community(self, community_id: str) -> dict[str, Any]:
        """Full detail for one community, including inter-community relations.

        Args:
            community_id: Id from ``bookstore_communities``.
        """
        community = self._bookstore.get_community(community_id)
        return community.model_dump(mode="json")

    async def search(
        self,
        query: str,
        book_ids: Optional[list[str]] = None,
        max_books: int = 3,
        expand_related: bool = False,
    ) -> dict[str, Any]:
        """Cross-book research search (catalog shortlist → tree search).

        Use for questions spanning the library ("which of my books
        discusses X and what do they say?"). Costs up to one LLM
        tree-walk per shortlisted book — keep ``max_books`` small.

        Args:
            query: Natural-language research question.
            book_ids: Restrict to these books; omit for an automatic
                catalog shortlist.
            max_books: Cap on books searched (clamped to 1-10).
            expand_related: When ``True``, widen the shortlist with
                each shortlisted book's depth-1 related books before
                searching — still capped by ``max_books``, no extra
                LLM call.
        """
        return await self._bookstore.search(
            query,
            book_ids=book_ids,
            max_books=max(1, min(max_books, 10)),
            expand_related=expand_related,
        )
