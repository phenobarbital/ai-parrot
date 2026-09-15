"""The Bookstore manager — catalogs + PageIndex trees per scope.

:class:`Bookstore` composes one :class:`~parrot.knowledge.bookstore.catalog.CatalogStore`
and one :class:`~parrot.knowledge.pageindex.toolkit.PageIndexToolkit`
per resolved library location (project first, then global), providing:

- the ingestion surface used by the ``bookstore`` CLI (:meth:`add_book`,
  :meth:`remove_book`, :meth:`refresh_card`), and
- the read surface wrapped by
  :class:`~parrot.knowledge.bookstore.toolkit.BookstoreToolkit` for
  agents (catalog search → ToC → in-book search → section read).

The whole library works without any LLM configured: ingestion falls
back to deterministic carding and searches run BM25-only.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

from .carding import (
    derive_toc,
    fallback_card_fields,
    generate_card_fields,
    sample_sections,
    slugify,
    unique_slug,
)
from .catalog import CatalogStore, merged_cards, merged_communities, merged_relations, merged_search
from .config import LibraryLocation
from .models import REL_WEIGHTS, BookCard, BookCommunity, BookRelation, CardDraft, RelateSummary
from .relations import (
    candidate_pairs,
    communities_from_result,
    detect_book_communities,
    deterministic_relations,
    fallback_label,
    judge_relations,
    label_community,
    llm_relations_from_draft,
)

logger = logging.getLogger(__name__)

_FORMAT_BY_SUFFIX = {
    ".pdf": "pdf",
    ".md": "md",
    ".markdown": "md",
    ".txt": "txt",
    ".epub": "epub",
    ".mobi": "mobi",
    # .doc (legacy binary) is deliberately absent: python-docx can't read it.
    ".docx": "docx",
}


def _other_endpoint(relation: BookRelation, anchor: str) -> Optional[str]:
    """The endpoint of ``relation`` that isn't ``anchor``, or ``None``.

    Returns ``None`` when ``anchor`` is neither endpoint — the relation
    simply doesn't touch it (e.g. while walking hop-2 candidates).
    """
    if relation.src_book_id == anchor:
        return relation.dst_book_id
    if relation.dst_book_id == anchor:
        return relation.src_book_id
    return None


def _relation_brief(
    other_id: str,
    hop: int,
    relation: BookRelation,
    via: Optional[str],
    cards_by_id: dict[str, BookCard],
) -> dict[str, Any]:
    """One :meth:`Bookstore.related_books` result row."""
    card = cards_by_id.get(other_id)
    return {
        "book": card.brief() if card is not None else {"book_id": other_id},
        "rel": relation.rel,
        "origin": relation.origin,
        "weight": relation.weight,
        "confidence": relation.confidence,
        "rationale": relation.rationale,
        "hop": hop,
        "via": via,
    }


class BookstoreError(RuntimeError):
    """User-facing bookstore failure (bad input, missing book, no LLM…)."""


async def docx_to_markdown(path: Path) -> str:
    """Convert a Word document to markdown via ``parrot_loaders``.

    Reuses ``MSWordLoader.docx_to_markdown`` (heading styles → markdown
    headings, tables → markdown tables). The import is lazy —
    ``ai-parrot-loaders`` is a separate distribution and core must not
    hard-depend on it — and the synchronous conversion is offloaded with
    :func:`asyncio.to_thread`. A document with no Word heading styles
    yields heading-less markdown and therefore a 0-chapter tree (the same
    accepted behaviour as the markdown route).

    Args:
        path: Path to the ``.docx`` file.

    Returns:
        The converted markdown.

    Raises:
        BookstoreError: When ``ai-parrot-loaders`` is not installed, or the
            document has no readable content.
    """
    try:
        from parrot_loaders.docx import MSWordLoader
    except ImportError as exc:
        raise BookstoreError(
            "DOCX support requires the ai-parrot-loaders package " "(pip install ai-parrot-loaders)"
        ) from exc
    loader = MSWordLoader(str(path))
    markdown = await asyncio.to_thread(loader.docx_to_markdown, path)
    if not (markdown or "").strip():
        raise BookstoreError(f"No readable content found in {path.name}")
    return markdown


class _NullAdapter:
    """Adapter stand-in when no LLM is configured.

    Exposes the two attributes :class:`PageIndexToolkit` dereferences at
    construction time (``model``, ``client``). ``ask()`` degrades to an
    empty answer so LLM-optional ingest passes (per-node summaries in
    ``md_to_tree``) simply produce no summaries instead of failing the
    whole import; ``ask_structured()``/``ask_with_finish_info()`` raise
    because their callers (two-step text ingest, PDF TOC detection/
    structuring, carding) cannot proceed without a model —
    :class:`Bookstore` guards those paths up front. The raise (rather
    than silently degrading, as ``ask()`` does) is deliberate: any call
    that reaches here bypassed that guard, so it should fail loudly
    instead of behaving as an unrelated `AttributeError`.
    """

    model: Optional[str] = None
    client: Optional[Any] = None

    async def ask(self, *args: Any, **kwargs: Any) -> str:
        return ""

    async def ask_structured(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("No LLM configured for the bookstore")

    async def ask_with_finish_info(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("No LLM configured for the bookstore")


class Bookstore:
    """Personal indexed library over one or more library locations.

    Args:
        locations: Ordered locations (project scope first) from
            :func:`~parrot.knowledge.bookstore.config.resolve_locations`.
        adapter: Optional heavy
            :class:`~parrot.knowledge.pageindex.llm_adapter.PageIndexLLMAdapter`.
            When ``None`` the library runs in degraded (no-LLM) mode:
            BM25-only search and deterministic carding.
        lightweight_model: Optional cheap model id for PageIndex helper
            calls. Ignored (with a warning) when ``adapter`` is ``None``.
    """

    def __init__(
        self,
        locations: list[LibraryLocation],
        adapter: Optional[Any] = None,
        lightweight_model: Optional[str] = None,
    ) -> None:
        if not locations:
            raise BookstoreError("No library locations resolved")
        self.locations = locations
        self.adapter = adapter
        if adapter is None and lightweight_model:
            logger.warning(
                "lightweight_model=%r ignored — no LLM adapter configured",
                lightweight_model,
            )
            lightweight_model = None
        self.lightweight_model = lightweight_model
        self.logger = logger
        self._catalogs: dict[str, CatalogStore] = {}
        self._toolkits: dict[str, PageIndexToolkit] = {}
        self._content_stores: dict[str, NodeContentStore] = {}

    @property
    def has_llm(self) -> bool:
        """Whether a real LLM adapter is configured."""
        return self.adapter is not None

    # ------------------------------------------------------------------
    # Per-scope lazy components
    # ------------------------------------------------------------------
    def _location(self, scope: str) -> LibraryLocation:
        for loc in self.locations:
            if loc.scope == scope:
                return loc
        raise BookstoreError(f"No {scope!r} library location available")

    def _catalog(self, scope: str) -> CatalogStore:
        if scope not in self._catalogs:
            self._catalogs[scope] = CatalogStore(self._location(scope).db_path)
        return self._catalogs[scope]

    def _toolkit(self, scope: str) -> PageIndexToolkit:
        if scope not in self._toolkits:
            loc = self._location(scope)
            loc.trees_dir.mkdir(parents=True, exist_ok=True)
            self._toolkits[scope] = PageIndexToolkit(
                adapter=self.adapter if self.adapter is not None else _NullAdapter(),
                storage_dir=loc.trees_dir,
                lightweight_model=self.lightweight_model,
            )
        return self._toolkits[scope]

    def _content_store(self, scope: str) -> NodeContentStore:
        if scope not in self._content_stores:
            self._content_stores[scope] = NodeContentStore(self._location(scope).trees_dir)
        return self._content_stores[scope]

    def _stores(self) -> list[tuple[str, CatalogStore]]:
        return [(loc.scope, self._catalog(loc.scope)) for loc in self.locations]

    def _all_taken_slugs(self) -> set[str]:
        """Slugs in use across EVERY scope (catalog rows + trees on disk).

        Book ids must be unique across scopes: ``resolve_book`` and the
        merged listings dedupe by ``book_id`` with project precedence,
        so a cross-scope collision would silently mask the other book.
        Reads are side-effect-free — uninitialized locations are
        inspected via the filesystem, never created.
        """
        taken: set[str] = set()
        for loc in self.locations:
            if loc.db_path.is_file():
                taken |= self._catalog(loc.scope).taken_slugs()
            if loc.trees_dir.is_dir():
                taken |= {p.stem for p in loc.trees_dir.glob("*.json")}
        return taken

    # ------------------------------------------------------------------
    # Read surface
    # ------------------------------------------------------------------
    def list_books(self) -> list[BookCard]:
        """All cards across scopes, project scope winning collisions."""
        return merged_cards(self._stores())

    def catalog_search(self, query: str, top_k: int = 8) -> list[BookCard]:
        """Lexical "which book covers X?" search over the fichas."""
        return merged_search(self._stores(), query, top_k=top_k)

    def resolve_book(self, book_id: str) -> tuple[BookCard, LibraryLocation]:
        """Find a card by id across scopes (project first).

        Raises:
            BookstoreError: When no scope holds ``book_id``.
        """
        for loc in self.locations:
            card = self._catalog(loc.scope).get(book_id)
            if card is not None:
                return card.model_copy(update={"scope": loc.scope}), loc
        raise BookstoreError(f"Unknown book {book_id!r} — use catalog_search/list_books first")

    def get_card(self, book_id: str) -> BookCard:
        """Full ficha for one book."""
        card, _ = self.resolve_book(book_id)
        return card

    def get_toc(self, book_id: str) -> dict[str, Any]:
        """Structured table of contents with node ids and page ranges."""
        card, _ = self.resolve_book(book_id)
        return {
            "book_id": card.book_id,
            "title": card.title,
            "toc_digest": card.toc_digest,
            "entries": [entry.model_dump() for entry in card.toc],
        }

    async def search_book(self, book_id: str, query: str, top_k: int = 8) -> list[dict[str, Any]]:
        """Hybrid search inside one book's tree.

        The LLM tree-walk runs only when an adapter is configured;
        otherwise this is BM25-only (requires the optional ``bm25s``).
        """
        card, loc = self.resolve_book(book_id)
        toolkit = self._toolkit(loc.scope)
        return await toolkit.search(
            tree_name=card.tree_name,
            query=query,
            top_k=top_k,
            use_bm25=True,
            use_llm_walk=self.has_llm,
        )

    def read_section(self, book_id: str, node_id: str) -> dict[str, Any]:
        """Load one section's markdown body (plus title/pages context).

        Falls back to the node summary when the content sidecar is
        missing.
        """
        card, loc = self.resolve_book(book_id)
        body = self._content_store(loc.scope).load(card.tree_name, node_id)
        entry = next((e for e in card.toc if e.node_id == node_id), None)
        if body is None and entry is None:
            raise BookstoreError(f"Unknown section {node_id!r} in book {book_id!r} — " "check bookstore_get_toc")
        return {
            "book_id": card.book_id,
            "book_title": card.title,
            "node_id": node_id,
            "title": entry.title if entry else None,
            "start_page": entry.start_page if entry else None,
            "end_page": entry.end_page if entry else None,
            "content": body or "",
        }

    def _expand_with_related(self, cards: list[BookCard]) -> list[BookCard]:
        """Widen ``cards`` with depth-1 related books (no LLM call).

        Pure SQL via :meth:`related_books` (already ordered strongest
        edge first); already-shortlisted books and neighbours reached
        from several shortlisted books are deduped. The caller applies
        ``max_books`` afterwards — this never decides how many books
        end up searched, only which ones are eligible.
        """
        seen = {card.book_id for card in cards}
        cards_by_id = {card.book_id: card for card in self.list_books()}
        expanded = list(cards)
        for card in cards:
            for item in self.related_books(card.book_id, depth=1):
                neighbor_id = item["book"]["book_id"]
                if neighbor_id in seen:
                    continue
                seen.add(neighbor_id)
                neighbor_card = cards_by_id.get(neighbor_id)
                if neighbor_card is not None:
                    expanded.append(neighbor_card)
        return expanded

    async def search(
        self,
        query: str,
        book_ids: Optional[list[str]] = None,
        max_books: int = 3,
        top_k: int = 5,
        expand_related: bool = False,
    ) -> dict[str, Any]:
        """Cross-book research search.

        Shortlists books via the catalog (or validates ``book_ids``),
        then searches each shortlisted tree — via the scoped LLM
        tree-walk when an adapter is configured, else per-book BM25.

        Args:
            query: Natural-language research question.
            book_ids: Explicit books to search; ``None`` = catalog
                shortlist.
            max_books: Cap on books searched (keep small — each book
                may cost an LLM call).
            top_k: Per-book result cap in the BM25 path.
            expand_related: When ``True``, widen the shortlist with
                depth-1 related books (:meth:`related_books`, no extra
                LLM call) before applying ``max_books`` — the cap still
                applies afterwards, so this can only narrow *which*
                books are searched, never how many.

        Returns:
            ``{"query", "books": [{book_id, title, scope, results|context}]}``.
        """
        if book_ids:
            cards = [self.resolve_book(b)[0] for b in book_ids]
        else:
            cards = self.catalog_search(query, top_k=max_books)
            if not cards:
                # Thin cards (e.g. fallback carding) may miss lexically;
                # for a small library, searching every book beats "empty".
                cards = self.list_books()
        if expand_related:
            cards = self._expand_with_related(cards)
        cards = cards[:max_books]
        if not cards:
            return {"query": query, "books": [], "status": "empty"}

        books: list[dict[str, Any]] = []
        if self.has_llm:
            by_scope: dict[str, list[BookCard]] = {}
            for card in cards:
                by_scope.setdefault(card.scope, []).append(card)
            for scope, scope_cards in by_scope.items():
                toolkit = self._toolkit(scope)
                scoped = await toolkit.search_documents_scoped(
                    tree_names=[c.tree_name for c in scope_cards],
                    query=query,
                )
                titles = {c.tree_name: c.title for c in scope_cards}
                for result in scoped.get("scoped_results", []):
                    tree = result.get("tree_name")
                    books.append(
                        {
                            "book_id": tree,
                            "title": titles.get(tree, tree),
                            "scope": scope,
                            **{k: v for k, v in result.items() if k != "tree_name"},
                        }
                    )
        else:
            for card in cards:
                results = await self.search_book(card.book_id, query, top_k=top_k)
                books.append(
                    {
                        "book_id": card.book_id,
                        "title": card.title,
                        "scope": card.scope,
                        "results": results,
                    }
                )
        return {"query": query, "books": books}

    # ------------------------------------------------------------------
    # Relations (Stage 1 deterministic + read path — FEAT-533)
    # ------------------------------------------------------------------
    def _visible_ids(self) -> set[str]:
        """Book ids visible to the caller across every scope."""
        return {card.book_id for card in self.list_books()}

    def _relations_store_for(self, book_id: str) -> CatalogStore:
        """The scope DB that should own edges whose ``src`` is ``book_id``.

        Cross-scope storage rule (spec §7): an edge lives in the DB of
        the scope that owns its ``src`` book.
        """
        _card, loc = self.resolve_book(book_id)
        return self._catalog(loc.scope)

    def _write_deterministic(self, relations: list[BookRelation], target_ids: Optional[set[str]] = None) -> None:
        """Persist deterministic edges, replacing prior ones for every target.

        First deletes every existing ``origin="deterministic"`` edge
        touching a book in ``target_ids``, from **every** scope store
        (an edge touching a target may have been physically stored in
        either partner's scope, depending on which side owns the
        cross-scope/canonical `src`, and that can change run to run as
        neighbours come and go) — then writes the new ``relations``,
        grouped by the scope DB that owns each edge's ``src``.

        Deleting by ``target_ids`` rather than only the ids that happen
        to appear in ``relations`` is what makes a re-run idempotent
        when recomputation yields **zero** matching edges for a target
        (e.g. a book's authors/topics changed such that it no longer
        shares anything with its old neighbours): an empty ``relations``
        list still correctly drops that target's now-stale edges,
        instead of leaving them behind forever.

        Args:
            relations: Edges to persist, typically the output of
                :func:`~parrot.knowledge.bookstore.relations.deterministic_relations`,
                already filtered to those touching a target.
            target_ids: Every book id this write is authoritative for.
                Defaults to the ids appearing in ``relations`` (the
                pre-existing, narrower behaviour) when omitted — callers
                recomputing Stage 1 for an explicit set of books should
                always pass it explicitly.
        """
        if target_ids is None:
            target_ids = {book_id for relation in relations for book_id in (relation.src_book_id, relation.dst_book_id)}
        for book_id in target_ids:
            for _scope, store in self._stores():
                store.delete_relations(book_id=book_id, origin="deterministic")

        by_scope: dict[str, list[BookRelation]] = {}
        for relation in relations:
            _card, loc = self.resolve_book(relation.src_book_id)
            by_scope.setdefault(loc.scope, []).append(relation)
        for scope, scoped_relations in by_scope.items():
            self._catalog(scope).upsert_relations(scoped_relations)

    def related_books(
        self,
        book_id: str,
        rel: Optional[str] = None,
        depth: int = 1,
        top_k: int = 10,
        min_confidence: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Walk the book graph outward from ``book_id`` (SQL-only, no LLM).

        Backs both the CLI ``bookstore related`` command and the
        ``bookstore_related_books`` MCP tool — synchronous and
        side-effect-free by design.

        Args:
            book_id: Origin book.
            rel: Optional relation kind filter.
            depth: Hops to walk from ``book_id`` — clamped to 1 or 2.
            top_k: Maximum results returned.
            min_confidence: Drop LLM edges below this confidence
                (deterministic/community edges have no confidence and
                are never filtered by this).

        Returns:
            Dicts ``{book, rel, origin, weight, confidence, rationale,
            hop, via}`` — ``book`` is the neighbour's :meth:`BookCard.brief`,
            ``via`` is the hop-1 book that led to a hop-2 result (``None``
            for hop-1). Ordered by hop ascending, then weight descending.
            When several edges reach the same book, the strongest
            (smallest hop, then largest weight) wins.

        Raises:
            BookstoreError: When ``book_id`` is unknown.
        """
        self.resolve_book(book_id)
        depth = max(1, min(depth, 2))
        visible = self._visible_ids()
        relations = merged_relations(self._stores(), visible)
        cards_by_id = {card.book_id: card for card in self.list_books()}

        def _matches(relation: BookRelation) -> bool:
            if rel is not None and relation.rel != rel:
                return False
            if relation.confidence is not None and relation.confidence < min_confidence:
                return False
            return True

        filtered = [r for r in relations if _matches(r)]

        best: dict[str, tuple[int, BookRelation, Optional[str]]] = {}

        def _consider(other_id: str, hop: int, relation: BookRelation, via: Optional[str]) -> None:
            if other_id == book_id or other_id not in cards_by_id:
                return
            current = best.get(other_id)
            if current is None or hop < current[0] or (hop == current[0] and relation.weight > current[1].weight):
                best[other_id] = (hop, relation, via)

        hop1_neighbors: set[str] = set()
        for relation in filtered:
            other = _other_endpoint(relation, book_id)
            if other is not None:
                hop1_neighbors.add(other)
                _consider(other, 1, relation, None)

        if depth == 2:
            for anchor in hop1_neighbors:
                for relation in filtered:
                    other = _other_endpoint(relation, anchor)
                    if other is not None:
                        _consider(other, 2, relation, anchor)

        results = [
            _relation_brief(other_id, hop, relation, via, cards_by_id)
            for other_id, (hop, relation, via) in best.items()
        ]
        results.sort(key=lambda item: (item["hop"], -item["weight"]))
        return results[:top_k]

    async def relate_books(
        self,
        book_ids: Optional[list[str]] = None,
        *,
        use_llm: bool = True,
        communities: bool = True,
        communities_only: bool = False,
        force: bool = False,
        resolution: float = 1.0,
    ) -> RelateSummary:
        """Compute and persist relations for ``book_ids`` (or every visible book).

        Runs Stage 1 (deterministic, always — unless ``communities_only``),
        Stage 2 (LLM conceptual relations, when ``use_llm and self.has_llm
        and not communities_only``), and Stage 3 (communities — a hook
        only in this task; see :meth:`_relate_stage3`, wired by TASK-2917).

        Args:
            book_ids: Explicit target book ids (validated via
                :meth:`resolve_book`), or ``None`` for every visible book.
            use_llm: Whether Stage 2 may run at all (still gated by
                :attr:`has_llm`).
            communities: Whether Stage 3 runs.
            communities_only: Skip Stage 1/2 entirely and only run
                Stage 3 (used by :meth:`add_folder`'s end-of-batch pass).
            force: Re-judge candidate pairs already logged in
                ``relation_judgements`` instead of skipping them.
            resolution: Forwarded to Stage 3's community detection.

        Returns:
            A :class:`RelateSummary` describing what ran.

        Raises:
            BookstoreError: An explicit ``book_ids`` entry is unknown.
        """
        all_cards = self.list_books()
        cards_by_id = {card.book_id: card for card in all_cards}

        if book_ids is None:
            targets = [card.book_id for card in all_cards]
        else:
            for book_id in book_ids:
                self.resolve_book(book_id)  # raises BookstoreError if unknown
            targets = list(book_ids)

        summary = RelateSummary(targets=targets)

        if not communities_only:
            now = datetime.now(timezone.utc).isoformat()
            det = deterministic_relations(all_cards, now=now)
            target_set = set(targets)
            touching_targets = [
                relation for relation in det if relation.src_book_id in target_set or relation.dst_book_id in target_set
            ]
            # Always call _write_deterministic (never guard on
            # touching_targets being non-empty) — a target whose
            # metadata change means it no longer shares anything with
            # its old neighbours must still have its stale edges
            # dropped; see _write_deterministic's own docstring.
            self._write_deterministic(touching_targets, target_set)
            summary.deterministic_edges = len(touching_targets)

            if not use_llm or not self.has_llm:
                summary.skipped_llm_reason = "no LLM configured" if not self.has_llm else "--no-llm"
            else:
                for book_id in targets:
                    card = cards_by_id.get(book_id)
                    if card is None:
                        continue
                    try:
                        store = self._relations_store_for(book_id)
                        judged = set() if force else store.judged_pairs(book_id)
                        fts_hits = self.catalog_search(card.summary or " ".join(card.topics), top_k=8)
                        candidates = candidate_pairs(
                            card,
                            all_cards,
                            det,
                            fts_hits,
                            judged,
                        )
                        if not candidates:
                            continue
                        model_name = getattr(self.adapter, "model", "") or ""
                        draft = await judge_relations(
                            self.adapter,
                            card,
                            candidates,
                            model_name=model_name,
                        )
                        summary.llm_prompts += 1
                        store.record_judgements(
                            book_id,
                            draft.judgements,
                            model=model_name,
                        )
                        # Replace only the pairs re-judged this run, so
                        # edges judged earlier from the *other* book's
                        # perspective survive (spec §7 asymmetry rule).
                        for judgement in draft.judgements:
                            store.delete_relation_pair(
                                book_id,
                                judgement.dst_book_id,
                                origin="llm",
                            )
                        rels = llm_relations_from_draft(card, draft, now=now)
                        if rels:
                            store.upsert_relations(rels)
                        summary.llm_edges += len(rels)
                    except Exception as exc:  # noqa: BLE001 — never abort the batch
                        logger.warning("relate: Stage 2 failed for %r: %s", book_id, exc)
                        summary.failed[book_id] = str(exc)

        if communities:
            await self._relate_stage3(resolution, summary)

        return summary

    async def _relate_stage3(self, resolution: float, summary: RelateSummary) -> None:
        """Stage 3: detect communities, label them, and persist (spec §3 Module 3).

        Always runs over the FULL merged+visible graph (community
        membership is global, never per-target) — ``resolution`` is
        the only tunable exposed through :meth:`relate_books`. Never
        raises: detection/labelling failures are caught and recorded
        as a note on ``summary``, leaving the previous partition (if
        any) untouched.
        """
        visible_cards = self.list_books()
        if len(visible_cards) < 3:
            # The library has genuinely shrunk below the threshold — the
            # previous partition (if any) describes membership that no
            # longer exists, so it is invalidated rather than left
            # stale (unlike the detection-failure path below, which
            # preserves a still-possibly-valid prior partition).
            self._clear_communities()
            summary.notes.append("communities: skipped (<3 books)")
            return
        visible_ids = {card.book_id for card in visible_cards}
        relations = [
            relation for relation in merged_relations(self._stores(), visible_ids) if relation.rel != "same_community"
        ]

        try:
            result, inter, _assembler = detect_book_communities(
                visible_cards,
                relations,
                resolution=resolution,
            )
        except Exception as exc:  # noqa: BLE001 — never abort the batch
            logger.warning("relate: Stage 3 detection failed: %s", exc)
            summary.notes.append(f"communities: failed ({exc})")
            return

        cards_by_id = {card.book_id: card for card in visible_cards}
        now = datetime.now(timezone.utc).isoformat()
        labels: dict[str, tuple[str, str, str]] = {}
        for community in result.communities:
            try:
                if self.has_llm:
                    draft = await label_community(self.adapter, community, cards_by_id)
                    labels[community.community_id] = (
                        draft.label,
                        draft.description,
                        "llm",
                    )
                else:
                    label, origin = fallback_label(community, cards_by_id)
                    labels[community.community_id] = (label, "", origin)
            except Exception as exc:  # noqa: BLE001 — never abort the batch
                logger.warning(
                    "relate: labelling failed for community %r: %s",
                    community.community_id,
                    exc,
                )
                label, origin = fallback_label(community, cards_by_id)
                labels[community.community_id] = (label, "", origin)

        book_communities = communities_from_result(
            result,
            inter,
            labels,
            cards_by_id,
            now=now,
        )
        self._communities_store().upsert_communities(book_communities)

        # same_community edges are rewritten from scratch every run —
        # membership (and therefore community_id) changes across runs.
        for _scope, store in self._stores():
            store.delete_relations(origin="community")

        same_community_weight = REL_WEIGHTS["same_community"]
        by_scope_edges: dict[str, list[BookRelation]] = {}
        for community in result.communities:
            for a, b in itertools.combinations(sorted(community.member_node_ids), 2):
                _card_a, loc = self.resolve_book(a)
                by_scope_edges.setdefault(loc.scope, []).append(
                    BookRelation(
                        src_book_id=a,
                        dst_book_id=b,
                        rel="same_community",
                        weight=same_community_weight,
                        origin="community",
                        computed_at=now,
                    )
                )
        for scope, edges in by_scope_edges.items():
            self._catalog(scope).upsert_relations(edges)

        node_to_community = result.node_to_community
        for card in visible_cards:
            community_id = node_to_community.get(card.book_id)
            label = labels[community_id][0] if community_id is not None else None
            loc_scope = self.resolve_book(card.book_id)[1].scope
            self._catalog(loc_scope).set_card_community(
                card.book_id,
                community_id,
                label,
            )

        summary.communities = len(result.communities)
        summary.notes.append(f"communities: {result.algorithm} ({len(result.communities)})")

    def _communities_store(self) -> CatalogStore:
        """The scope DB that receives the ``communities`` table this run.

        One merged-graph partition, stored once — project DB when a
        project scope exists, else global (spec §2 step 3).
        """
        for loc in self.locations:
            if loc.scope == "project":
                return self._catalog("project")
        return self._catalog(self.locations[0].scope)

    def _clear_communities(self) -> None:
        """Invalidate the persisted community partition and every card's stamp.

        Community membership is a property of the *whole* merged graph
        — removing a book (or the library falling under Stage 3's
        3-book threshold) invalidates every existing community's
        membership at once, so there is no way to "repair" the old
        partition in place. Clearing it here — rather than leaving
        stale rows/labels behind until the next successful ``relate``
        — keeps :meth:`communities`/:meth:`get_community` from ever
        reporting a book that no longer exists.
        """
        for _scope, store in self._stores():
            store.upsert_communities([])
        for card in self.list_books():
            self._catalog(card.scope).set_card_community(card.book_id, None, None)

    def communities(self) -> list[BookCommunity]:
        """All communities from the merged graph (read-only, SQL-only)."""
        return merged_communities(self._stores())

    def get_community(self, community_id: str) -> BookCommunity:
        """One community by id.

        Raises:
            BookstoreError: When ``community_id`` is unknown.
        """
        for community in self.communities():
            if community.community_id == community_id:
                return community
        raise BookstoreError(f"Unknown community {community_id!r}")

    # ------------------------------------------------------------------
    # export-wiki (CLI-only — spec §4 Non-Goals: no write tool over MCP)
    # ------------------------------------------------------------------
    async def export_wiki(
        self,
        output_dir: Optional[Path] = None,
        *,
        scope: str = "project",
        register: bool = True,
    ) -> dict[str, Any]:
        """Project the book graph into a dedicated wikitoolkit plane.

        Lazily imports ``parrot.knowledge.wiki``/``graphindex.export_html``
        (via ``.wiki_export``) — the MCP read path never touches this
        method, so ``parrot.knowledge.wiki`` never enters ``sys.modules``
        there.

        Args:
            output_dir: Export directory; defaults to
                ``<library>/wiki`` for ``scope``.
            scope: Which library location to export (``"project"`` or
                ``"global"``); cards from every scope are still exported
                as pages (the graph is the full merged one), this only
                picks the output directory and the default namespace
                registry.
            register: Register namespace ``"bookstore"`` afterwards
                (project's ``.parrot/wiki.json`` normally, global
                ``wikis.json`` when ``scope="global"`` or no git root is
                found).

        Returns:
            ``{"pages", "edges", "html", "json", "registered_in"}`` —
            ``registered_in`` is the registry path written, or ``None``
            when ``register=False``.

        Raises:
            BookstoreError: The wiki/graphindex packages are not
                importable, or namespace registration conflicts with an
                existing, different entry.
        """
        from .wiki_export import default_wiki_dir, export_plane, register_namespace

        loc = self._location(scope)
        out_dir = Path(output_dir) if output_dir is not None else default_wiki_dir(loc)

        cards = self.list_books()
        visible_ids = {card.book_id for card in cards}
        relations = merged_relations(self._stores(), visible_ids)

        # Rebuild the clustering graph purely for graph.html — never
        # persisted here (Bookstore.relate_books/_relate_stage3 owns
        # persistence). Prefer already-persisted labels over freshly
        # (re-)derived fallback ones when a partition exists.
        result, inter, assembler = detect_book_communities(cards, relations)
        persisted_labels = {c.community_id: c.label for c in self.communities()}
        if persisted_labels:
            relabelled = [
                (
                    community.model_copy(update={"label": persisted_labels[community.community_id]})
                    if community.community_id in persisted_labels
                    else community
                )
                for community in result.communities
            ]
            result = result.model_copy(update={"communities": relabelled})

        stats = await export_plane(cards, relations, result, inter, assembler, out_dir)

        registered_in: Optional[str] = None
        if register:
            try:
                from parrot.knowledge.wiki.project import find_project_root
            except ImportError as exc:
                raise BookstoreError(
                    "export-wiki requires the wiki/graphindex packages " "(pip install ai-parrot[wiki])"
                ) from exc
            git_root = None if scope == "global" else find_project_root(loc.root)
            registered_in = str(register_namespace(out_dir, scope=scope, git_root=git_root))

        return {**stats, "registered_in": registered_in}

    # ------------------------------------------------------------------
    # Ingestion surface (CLI-only)
    # ------------------------------------------------------------------
    async def add_book(
        self,
        file_path: str | Path,
        scope: str = "project",
        title: Optional[str] = None,
        authors: Optional[list[str]] = None,
        topics: Optional[list[str]] = None,
        force: bool = False,
        *,
        relate: bool = False,
    ) -> tuple[BookCard, str]:
        """Index a book file and catalog its ficha.

        Args:
            file_path: Source PDF, Markdown, text, EPUB, MOBI, or DOCX book.
            scope: Target library (``"project"`` or ``"global"``).
            title: Override the carded title (also seeds the slug).
            authors: Override the carded authors.
            topics: Override the carded topics.
            force: Re-index even when the same file (by sha256) is
                already catalogued.
            relate: When ``True``, run :meth:`relate_books` for just
                this book (Stages 1-2 only, no communities) right after
                cataloguing it. ``False`` by default (G3: plain ``add``
                must never call the relation LLM).

        Returns:
            ``(card, status)`` where status is ``"added"``, ``"updated"``
            or ``"skipped"`` (sha match without ``force``).

        Raises:
            BookstoreError: Unsupported format, missing file, ``.pdf``
                or ``.txt`` without an LLM, or EPUB without
                ``ai-parrot-loaders``.
        """
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            raise BookstoreError(f"File not found: {path}")
        fmt = _FORMAT_BY_SUFFIX.get(path.suffix.lower())
        if fmt is None:
            raise BookstoreError(f"Unsupported format {path.suffix!r} — " f"supported: {sorted(_FORMAT_BY_SUFFIX)}")

        catalog = self._catalog(scope)
        payload = await asyncio.to_thread(path.read_bytes)
        sha256 = hashlib.sha256(payload).hexdigest()
        existing = catalog.find_by_sha(sha256)
        status = "added"
        if existing is not None:
            if not force:
                return existing.model_copy(update={"scope": scope}), "skipped"
            status = "updated"

        toolkit = self._toolkit(scope)
        if status == "updated":
            slug = existing.book_id
            await toolkit.delete_tree(slug)
        else:
            slug = unique_slug(slugify(title or path.stem), self._all_taken_slugs())

        await toolkit.create_tree(slug, doc_name=title or path.stem)
        doc_description = ""
        try:
            if fmt == "pdf":
                if not self.has_llm:
                    raise BookstoreError(
                        "PDF ingest needs an LLM to detect and structure "
                        "the table of contents — configure one (--llm) "
                        "or convert to markdown/text first"
                    )
                result = await toolkit.import_pdf(
                    tree_name=slug,
                    pdf_path=str(path),
                    with_summaries=self.has_llm,
                    with_doc_description=self.has_llm,
                )
                doc_description = result.get("doc_description") or ""
            elif fmt == "md":
                await toolkit.insert_markdown(
                    tree_name=slug,
                    markdown=await asyncio.to_thread(path.read_text, encoding="utf-8"),
                    doc_name=title or path.stem,
                )
            elif fmt == "txt":
                if not self.has_llm:
                    raise BookstoreError(
                        "Plain-text ingest needs an LLM to structure the "
                        "content — configure one or convert to markdown"
                    )
                await toolkit.insert_content(
                    tree_name=slug,
                    content=await asyncio.to_thread(path.read_text, encoding="utf-8"),
                )
            elif fmt == "docx":
                markdown = await self._docx_to_markdown(path)
                await toolkit.insert_markdown(
                    tree_name=slug,
                    markdown=markdown,
                    doc_name=title or path.stem,
                )
            else:  # ebook
                sections = await self._ebook_sections(path)
                await toolkit.insert_ebook(
                    tree_name=slug,
                    sections=sections,
                )
        except Exception:
            # Never leave a half-imported tree behind an errored add.
            try:
                await toolkit.delete_tree(slug)
            except Exception:  # noqa: BLE001 — best-effort cleanup
                logger.debug("Cleanup of tree %r failed", slug, exc_info=True)
            raise

        tree = await toolkit.get_tree(slug)
        toc_entries, toc_digest = derive_toc(tree)
        draft = await self._draft_card(
            path=path,
            tree_name=slug,
            scope=scope,
            doc_description=doc_description or tree.get("doc_description") or "",
            toc_digest=toc_digest,
            toc_entries=toc_entries,
        )
        card_origin = "fallback" if not self.has_llm else "llm"
        if title or authors or topics:
            card_origin = "manual"

        page_count = max(
            (e.end_page for e in toc_entries if e.end_page is not None),
            default=None,
        )
        card = BookCard(
            book_id=slug,
            title=title or draft.title,
            authors=authors if authors is not None else draft.authors,
            year=draft.year,
            language=draft.language,
            topics=topics if topics is not None else draft.topics,
            summary=draft.summary,
            toc_digest=toc_digest,
            toc=toc_entries,
            tree_name=slug,
            scope=scope,  # type: ignore[arg-type]
            source_path=str(path),
            source_sha256=sha256,
            source_format=fmt,  # type: ignore[arg-type]
            page_count=page_count,
            chapter_count=sum(1 for e in toc_entries if e.depth == 1),
            added_at=datetime.now(timezone.utc).isoformat(),
            card_origin=card_origin,  # type: ignore[arg-type]
            genre=draft.genre,  # type: ignore[arg-type]
            traditions=draft.traditions,
            period=draft.period,
        )
        catalog.upsert(card)
        if relate:
            await self.relate_books([card.book_id], communities=False)
        return card, status

    async def _draft_card(
        self,
        path: Path,
        tree_name: str,
        scope: str,
        doc_description: str,
        toc_digest: str,
        toc_entries: list,
    ) -> CardDraft:
        if not self.has_llm:
            return fallback_card_fields(path, toc_entries)
        loader = self._content_store(scope).loader_for(tree_name)
        node_ids = [e.node_id for e in toc_entries if e.node_id]
        samples = sample_sections(loader, node_ids)
        try:
            return await generate_card_fields(
                self.adapter,
                filename=path.name,
                doc_description=doc_description,
                toc_digest=toc_digest,
                samples=samples,
            )
        except Exception as exc:  # noqa: BLE001 — carding must not block ingest
            logger.warning("LLM carding failed (%s); using fallback card", exc)
            return fallback_card_fields(path, toc_entries)

    async def _docx_to_markdown(self, path: Path) -> str:
        """Convert a Word document to markdown.

        Thin delegation to the module-level :func:`docx_to_markdown` helper
        so other card families (contracts, FEAT-539) can reuse the exact
        same conversion, lazy import and error behaviour.

        Args:
            path: Path to the ``.docx`` file.

        Returns:
            The converted markdown.

        Raises:
            BookstoreError: When ``ai-parrot-loaders`` is missing or the
                document has no readable content.
        """
        return await docx_to_markdown(path)

    async def _epub_to_markdown(self, path: Path) -> str:
        """Render EPUB sections as Markdown for callers needing a text export."""
        from parrot.loaders.ebook import EbookSection, ebook_markdown

        sections = await self._ebook_sections(path)
        return ebook_markdown([EbookSection.model_validate(section) for section in sections])

    async def _ebook_sections(self, path: Path) -> list[dict[str, Any]]:
        """Load the source ebook hierarchy without a Markdown round trip."""
        from parrot.loaders.ebook import ebook_sections

        try:
            if path.suffix.lower() == ".mobi":
                from parrot_loaders.mobiloader import MobiLoader as Loader
            else:
                from parrot_loaders.epubloader import EpubLoader as Loader

            loader = Loader(
                str(path),
                as_markdown=True,
                per_chapter=True,
                include_toc_document=False,
            )
        except ImportError as exc:
            raise BookstoreError(
                "EPUB/MOBI support requires the ai-parrot-loaders package "
                "with its ebook extra (uv pip install 'ai-parrot-loaders[ebook]')"
            ) from exc
        try:
            documents = await loader._load(path)
        except Exception as exc:
            raise BookstoreError(f"Could not load ebook {path.name}: {exc}") from exc
        sections = ebook_sections(documents)
        if not sections:
            raise BookstoreError(f"No readable chapters found in {path.name}")
        return [section.model_dump() for section in sections]

    @staticmethod
    def iter_folder_files(folder: str | Path, recursive: bool = False) -> tuple[list[Path], list[Path]]:
        """Enumerate a folder's ingestable files.

        Args:
            folder: Directory to scan.
            recursive: Also descend into subdirectories.

        Returns:
            ``(supported, ignored)`` — files whose suffix ``add_book``
            can ingest, and the rest — both in stable alphabetical
            order (relative path).

        Raises:
            BookstoreError: When ``folder`` is not a directory.
        """
        root = Path(folder).expanduser().resolve()
        if not root.is_dir():
            raise BookstoreError(f"Not a directory: {root}")
        pattern = "**/*" if recursive else "*"
        supported: list[Path] = []
        ignored: list[Path] = []
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            if path.suffix.lower() in _FORMAT_BY_SUFFIX:
                supported.append(path)
            else:
                ignored.append(path)
        return supported, ignored

    async def add_folder(
        self,
        folder: str | Path,
        scope: str = "project",
        recursive: bool = False,
        force: bool = False,
        *,
        relate: bool = False,
    ) -> dict[str, Any]:
        """Index every supported file in a folder, one book per file.

        Files are processed sequentially — each book can be a
        minutes-long LLM batch, and sequential ingest is friendly to
        provider rate limits. A failing file never stops the loop; its
        error is recorded and the next file proceeds.

        Args:
            folder: Directory holding the books.
            scope: Target library (``"project"`` or ``"global"``).
            recursive: Also ingest files in subdirectories.
            force: Re-index files already catalogued (by sha256).
            relate: When ``True``, each new book is related right after
                its own ingest (Stage 1-2 only, per file — same as
                ``add_book(relate=True)``); once the whole folder is
                processed, one Stage-3-only
                ``relate_books(None, communities_only=True)`` pass runs
                if at least one file was added/updated — communities
                are computed once over the whole merged library, never
                per file.

        Returns:
            ``{"folder", "results": [{file, status, book_id?, error?}],
            "ignored": [paths]}`` where status is ``added`` /
            ``updated`` / ``skipped`` / ``failed``.
        """
        supported, ignored = self.iter_folder_files(folder, recursive=recursive)
        results: list[dict[str, Any]] = []
        any_succeeded = False
        for path in supported:
            try:
                card, status = await self.add_book(path, scope=scope, force=force, relate=relate)
                results.append({"file": str(path), "status": status, "book_id": card.book_id})
                if status in ("added", "updated"):
                    any_succeeded = True
            except Exception as exc:  # noqa: BLE001 — keep the loop alive
                logger.warning("Failed to ingest %s: %s", path, exc)
                results.append({"file": str(path), "status": "failed", "error": str(exc)})
        if relate and any_succeeded:
            await self.relate_books(None, communities_only=True)
        return {
            "folder": str(Path(folder).expanduser().resolve()),
            "results": results,
            "ignored": [str(p) for p in ignored],
        }

    async def remove_book(self, book_id: str) -> bool:
        """Remove a book — catalog row, PageIndex tree, and graph edges.

        Edges touching ``book_id`` may live in either scope's DB (the
        scope owning an edge's ``src`` — spec §7 cross-scope rule), so
        the relation/judgement cascade runs across every store, not
        just the book's own scope.

        Any persisted community partition is also invalidated (spec §7:
        community ids are membership hashes, so removing a member
        changes every affected community's identity at once — there is
        no way to "repair" the old partition in place). The next
        successful ``relate_books(communities=True)`` recomputes it;
        until then, ``communities()``/``get_community()`` correctly
        report nothing rather than a book that no longer exists.
        """
        card, loc = self.resolve_book(book_id)
        toolkit = self._toolkit(loc.scope)
        try:
            await toolkit.delete_tree(card.tree_name)
        except Exception:  # noqa: BLE001 — the tree may already be gone
            logger.warning("Tree %r missing while removing book %r", card.tree_name, book_id)
        for _scope, store in self._stores():
            store.delete_relations(book_id=book_id)
            store.delete_judgements(book_id)
        removed = self._catalog(loc.scope).remove(book_id)
        if removed:
            self._clear_communities()
        return removed

    async def refresh_card(self, book_id: str) -> BookCard:
        """Re-run carding on an existing tree (e.g. after enabling an LLM)."""
        card, loc = self.resolve_book(book_id)
        tree = await self._toolkit(loc.scope).get_tree(card.tree_name)
        toc_entries, toc_digest = derive_toc(tree)
        draft = await self._draft_card(
            path=Path(card.source_path),
            tree_name=card.tree_name,
            scope=loc.scope,
            doc_description=tree.get("doc_description") or "",
            toc_digest=toc_digest,
            toc_entries=toc_entries,
        )
        updated = card.model_copy(
            update={
                "title": draft.title or card.title,
                "authors": draft.authors or card.authors,
                "year": draft.year or card.year,
                "language": draft.language or card.language,
                "topics": draft.topics or card.topics,
                "summary": draft.summary or card.summary,
                "toc_digest": toc_digest,
                "toc": toc_entries,
                "card_origin": "llm" if self.has_llm else "fallback",
                # draft.genre defaults to the non-empty sentinel "other"
                # (unlike traditions=[]/period=None, which are already
                # falsy) — "draft.genre or card.genre" would therefore
                # ALWAYS pick draft.genre and silently downgrade a
                # previously-classified card back to "other" on every
                # no-LLM/fallback refresh. Only override when the draft
                # actually classified something.
                "genre": draft.genre if draft.genre != "other" else card.genre,
                "traditions": draft.traditions or card.traditions,
                "period": draft.period or card.period,
                # community_id/community_label are intentionally absent
                # here — they are not carding outputs and must survive
                # a refresh untouched (Bookstore.relate_books owns them).
            }
        )
        self._catalog(loc.scope).upsert(updated)
        return updated
