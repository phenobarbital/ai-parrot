"""BookstoreToolkit — the read-only agent surface of the library.

Every public async method auto-becomes a ``bookstore_*`` tool via
:class:`~parrot.tools.toolkit.AbstractToolkit`. The surface is
deliberately small and funnel-shaped for research:

0. ``bookstore_find_books`` — which books treat X, and where (librarian's sectors first)
1. ``bookstore_catalog_search`` — which book covers X? (cheap, no LLM)
1b. ``bookstore_related_books`` / ``bookstore_communities`` — expand by
    the book graph before opening anything (FEAT-533)
2. ``bookstore_get_toc`` — orient inside the chosen book
3. ``bookstore_search_book`` — targeted in-book hybrid search
4. ``bookstore_agentic_retrieve`` — validated, cited research within one book
5. ``bookstore_read_section`` — read only the sections that matter

Ingestion/removal is NOT exposed here — managing the library is the
``bookstore`` CLI's job (indexing a book is a minutes-long LLM batch,
the wrong shape for a stdio tool call, same reasoning that keeps
``bookstore relate``/``export-wiki`` CLI-only).
"""

from __future__ import annotations

import asyncio
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
    read_tools: frozenset[str] = frozenset(
        {
            "agentic_retrieve",
            "catalog_search",
            "communities",
            "find_books",
            "get_card",
            "get_community",
            "get_toc",
            "list_books",
            "outline",
            "read_pages",
            "read_section",
            "read_segments",
            "related_books",
            "search",
            "search_book",
        }
    )

    def __init__(self, bookstore: Bookstore, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._bookstore = bookstore

    async def find_books(self, query: str, top_k: int = 5) -> dict[str, Any]:
        """Which books of the library treat a topic, and where — START HERE.

        Answers from the librarian's sectors (the library notebook) with direct pointers to the
        table-of-contents entries; falls back to catalog search when no sector matches.

        Args:
            query: Topic or keywords (e.g. "stoic ethics").
            top_k: Maximum sectors or books returned (clamped to 1-50).

        Returns:
            ``{"source": "sectors", "sectors": [{code, title, books: [{book_id, title, scope,
            entries}]}]}``, or ``{"source": "catalog_fts", "books": [...], "hint": ...}`` when no
            sector matched. Use ``book_id`` + entry ``node_id`` with ``bookstore_read_section``.
        """
        return await self._bookstore.find_books(query, top_k=max(1, min(top_k, 50)))

    async def catalog_search(self, query: str, top_k: int = 8) -> list[dict[str, Any]]:
        """Find which books cover a topic by their catalog cards (lexical fallback of find_books).

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
        return await asyncio.to_thread(self._bookstore.get_toc, book_id)

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

    async def agentic_retrieve(
        self,
        book_id: str,
        query: str,
        top_k: int = 5,
        draft_answer: bool = True,
        budget_chars: Optional[int] = None,
        max_reads: Optional[int] = None,
        timeout_s: Optional[float] = None,
    ) -> dict[str, Any]:
        """Research one book with validated citations; requires PARROT_BOOKSTORE_LLM.

        Args:
            book_id: Stable identifier of the indexed book to research.
            query: Research question for the bounded reading loop.
            top_k: Number of first-stage candidates to consider.
            draft_answer: Whether to ask the model for a final answer.
            budget_chars: Optional total character budget for evidence reads.
            max_reads: Optional maximum number of evidence reads.
            timeout_s: Optional total request timeout in seconds.

        Returns:
            Validated evidence and citations decorated with book identity.

        Raises:
            BookstoreError: If indexed segments or a compatible LLM are unavailable.
            ValueError: If a numeric argument is invalid.
        """
        return await self._bookstore.agentic_retrieve(
            book_id,
            query,
            top_k=top_k,
            draft_answer=draft_answer,
            budget_chars=budget_chars,
            max_reads=max_reads,
            timeout_s=timeout_s,
        )

    async def read_section(self, book_id: str, node_id: str) -> dict[str, Any]:
        """Read one section's full markdown content.

        Cite results as: *book title*, section title, pp. start-end.

        Args:
            book_id: The book.
            node_id: Section id from ``bookstore_get_toc`` or
                ``bookstore_search_book``.
        """
        return await asyncio.to_thread(self._bookstore.read_section, book_id, node_id)

    async def read_pages(
        self, book_id: str, pages: str, max_chars: int = 12000, cursor: Optional[str] = None
    ) -> dict[str, Any]:
        """Read pages of a book, e.g. ``pages="5-7,12"``.

        Returns quoted book text split into segments; cite a segment by its ``address.label``
        (e.g. *p. 12 ¶3*). When ``truncated`` is true, call again with ``cursor=next_cursor``.

        Args:
            book_id: The book.
            pages: Page ranges, comma separated.
            max_chars: Character budget for this call.
            cursor: ``next_cursor`` from a previous call.
        """
        return await self._bookstore.read_pages(book_id, pages, max_chars=max_chars, cursor=cursor)

    async def read_segments(
        self,
        book_id: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        node_id: Optional[str] = None,
        max_chars: int = 12000,
        cursor: Optional[str] = None,
        expected_revision: Optional[str] = None,
    ) -> dict[str, Any]:
        """Read paragraphs (segments) of a book by position ``[start, end)`` or one section's own text.

        Returns quoted book text; cite a segment by its ``address.label`` (e.g. *Setup > Install ¶2*).
        When ``truncated`` is true, call again with ``cursor=next_cursor``.

        Args:
            book_id: The book.
            start: First segment position (inclusive).
            end: Last segment position (exclusive).
            node_id: Section id from ``bookstore_get_toc``; reads only that section's own paragraphs.
            max_chars: Character budget for this call.
            cursor: ``next_cursor`` from a previous call.
            expected_revision: Optional revision that the returned snapshot must match.

        Returns:
            Citable segments from the matching book snapshot.

        Raises:
            RevisionMismatchError: If the returned snapshot has a different revision.
            BookstoreError: If the segments cannot be read.
        """
        return await self._bookstore.read_segments(
            book_id,
            start=start,
            end=end,
            node_id=node_id,
            max_chars=max_chars,
            cursor=cursor,
            expected_revision=expected_revision,
        )

    async def outline(self, book_id: str, node_id: Optional[str] = None, max_depth: int = 3) -> dict[str, Any]:
        """Compact outline of a book (or one section): titles, node ids, pages and paragraph counts.

        Cheaper than ``bookstore_get_toc`` for deciding what to read next.

        Args:
            book_id: The book.
            node_id: Outline only this section's subtree.
            max_depth: How many levels to include.
        """
        return await self._bookstore.outline(book_id, node_id=node_id, max_depth=max_depth)

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
