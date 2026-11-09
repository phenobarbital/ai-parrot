"""Stage-1 Bookstore origin returning revision-pinned single-segment evidence (FEAT-858).

``BookstoreOrigin`` runs only the Bookstore stage-1 search (catalog shortlist plus
per-book LLM tree-walk or BM25) and bounded per-node segment reads. Every emitted
hit is ONE segment's exact text, clipped to the per-node ``excerpt_chars`` allowance
and verified against the immutable document revision the read returned. It never
runs the agentic reading loop.

Per-request diagnostics (skipped legacy books, stale or missing revisions, invalid
excerpts, failed reads) are kept in local variables of one collector call and
surfaced through :meth:`BookstoreOrigin.search_section` — never in mutable
instance state, so concurrent requests cannot leak notes into each other.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from parrot.models import OriginHit, OriginSection, SearchOriginKind
from parrot.knowledge.pageindex.segment_store import SegmentStore
from parrot.knowledge.pageindex.citations import find_any_match
from parrot_tools.multistoresearch.origins.base import SearchOrigin

if TYPE_CHECKING:  # pragma: no cover — type hints only; keeps Bookstore out of eager imports
    from parrot.knowledge.bookstore.library import Bookstore
    from parrot.knowledge.pageindex.segments import DocumentRevision

_VALID_SCOPES = ("project", "global")
_MAX_BOOKS_LIMIT = 10
_TOP_K_LIMIT = 50
_READ_CONCURRENCY = 4

logger = logging.getLogger(__name__)


def _positive_int(name: str, value: Any, upper: Optional[int] = None) -> int:
    """Return ``value`` when it is a positive int (bools rejected) within ``upper``.

    Args:
        name: Parameter name used in the error message.
        value: Candidate value.
        upper: Optional inclusive upper bound.

    Raises:
        ValueError: When ``value`` is not a positive int or exceeds ``upper``.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {value!r}")
    if upper is not None and value > upper:
        raise ValueError(f"{name} must be <= {upper}, got {value!r}")
    return value


def _segment_label(page: Optional[int], ordinal: int, section: Optional[list[str]]) -> str:
    """Human label matching PageIndex's segment address label (``p. 12 ¶3``)."""
    para = f"¶{ordinal + 1}"
    if page is not None:
        return f"p. {page} {para}"
    if section:
        return f"{' > '.join(section)} {para}"
    return para


@dataclass
class _Candidate:
    """One (book, node) pair proposed by stage 1, in stable input order."""

    book_id: str
    book_title: str
    scope: Optional[str]
    node_id: str
    score: Optional[float]


@dataclass
class _Diagnostics:
    """Request-local skip counters for one collector call."""

    legacy_books: set[str] = field(default_factory=set)
    stale_revisions: int = 0
    invalid_excerpts: int = 0
    failed_reads: int = 0

    def note(self, emitted: int) -> Optional[str]:
        """Render the skip counts as an LLM-readable note, or ``None`` when nothing was skipped."""
        parts: list[str] = []
        if self.legacy_books:
            parts.append(f"{len(self.legacy_books)} legacy book(s) without segments")
        if self.stale_revisions:
            parts.append(f"{self.stale_revisions} stale or missing revision(s)")
        if self.invalid_excerpts:
            parts.append(f"{self.invalid_excerpts} invalid excerpt(s)")
        if self.failed_reads:
            parts.append(f"{self.failed_reads} failed read(s)")
        if not parts:
            return None
        prefix = "all candidate evidence was skipped" if emitted == 0 else "some candidate evidence was skipped"
        return f"{prefix}: " + ", ".join(parts)


class BookstoreOrigin(SearchOrigin):
    """Bounded stage-1 Bookstore search with immutable citation metadata.

    Args:
        bookstore: The :class:`~parrot.knowledge.bookstore.library.Bookstore` facade.
        scope: Optional scope filter (``"project"`` or ``"global"``).
        book_ids: Optional explicit book filter; unknown ids raise at search time.
        max_books: Books searched per request (1..10).
        top_k: Candidate nodes per book (1..50).
        excerpt_chars: Per-node excerpt allowance in characters (positive).
        name: Adapter name. Defaults to ``"bookstore"``.
        description: LLM-readable explanation of this origin.
        timeout: Optional positive finite timeout in seconds for direct ``search``
            calls and the per-origin toolkit timeout.

    Raises:
        ValueError: On invalid limits, scope, book ids or timeout.
    """

    kind = SearchOriginKind.BOOKSTORE
    supports_fts = False

    def __init__(
        self,
        bookstore: Bookstore,
        *,
        scope: Optional[str] = None,
        book_ids: Optional[list[str]] = None,
        max_books: int = 3,
        top_k: int = 5,
        excerpt_chars: int = 600,
        name: str = "bookstore",
        description: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        if bookstore is None:
            raise ValueError("bookstore is required")
        if scope is not None and scope not in _VALID_SCOPES:
            raise ValueError(f"scope must be one of {_VALID_SCOPES} or None, got {scope!r}")
        if book_ids is not None:
            if isinstance(book_ids, (str, bytes)) or not isinstance(book_ids, (list, tuple)):
                raise ValueError("book_ids must be a list of book id strings")
            cleaned: list[str] = []
            for book_id in book_ids:
                if not isinstance(book_id, str) or not book_id.strip():
                    raise ValueError(f"book_ids must contain non-empty strings, got {book_id!r}")
                if book_id not in cleaned:
                    cleaned.append(book_id)
            book_ids = cleaned
        if timeout is not None:
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
                raise ValueError(f"timeout must be a positive finite number, got {timeout!r}")
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError(f"timeout must be a positive finite number, got {timeout!r}")
            timeout = float(timeout)
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")

        self.bookstore = bookstore
        self.scope = scope
        self.book_ids = book_ids
        self.max_books = _positive_int("max_books", max_books, _MAX_BOOKS_LIMIT)
        self.top_k = _positive_int("top_k", top_k, _TOP_K_LIMIT)
        self.excerpt_chars = _positive_int("excerpt_chars", excerpt_chars)
        self.name = name
        self.description = description or (
            "Bookstore origin — personal indexed book library. Each hit is an exact, "
            "revision-pinned excerpt of one book segment with a citation in "
            "metadata['citation']; scores are origin-native."
        )
        self.timeout = timeout
        self.logger = logger

    async def search(self, query: str, k: int) -> list[OriginHit]:
        """Return at most ``k`` evidence hits in stable native order.

        Args:
            query: The search query text.
            k: Maximum number of hits to return; ``k <= 0`` returns ``[]`` without searching.

        Returns:
            Verified single-segment hits ranked ``1..N``.

        Raises:
            TimeoutError: When the configured ``timeout`` elapses (child reads are cancelled).
        """
        if self.timeout is not None:
            section = await asyncio.wait_for(self._collect(query, k), timeout=self.timeout)
        else:
            section = await self._collect(query, k)
        return section.hits

    async def search_section(self, query: str, k: int) -> OriginSection:
        """Return hits and request-local skip counts; backend failures still raise.

        The enclosing toolkit applies its per-origin timeout around this call.

        Args:
            query: The search query text.
            k: Maximum number of hits to return.

        Returns:
            A successful section whose ``note`` counts skipped evidence, if any.
        """
        return await self._collect(query, k)

    # ------------------------------------------------------------------
    # Collector
    # ------------------------------------------------------------------
    def _section(self, hits: list[OriginHit], note: Optional[str]) -> OriginSection:
        return OriginSection(
            origin=self.name,
            origin_kind=self.kind,
            description=self.description,
            status="ok",
            note=note,
            hits=hits,
        )

    def _filtered_book_ids(self, query: str) -> Optional[list[str]]:
        """Return the shortlisted book ids under the configured filters.

        Returns ``None`` when no filter is configured (Bookstore shortlists itself).

        Raises:
            BookstoreError: When an explicitly configured book id is unknown.
        """
        if self.scope is None and self.book_ids is None:
            return None
        visible = self.bookstore.list_books()
        by_id = {card.book_id: card for card in visible}
        if self.book_ids is not None:
            unknown = [book_id for book_id in self.book_ids if book_id not in by_id]
            if unknown:
                from parrot.knowledge.bookstore.library import BookstoreError

                raise BookstoreError(
                    f"Unknown book id(s) configured for origin {self.name!r}: {unknown} — "
                    "use list_books to find valid ids"
                )
            allowed = [by_id[book_id] for book_id in self.book_ids]
        else:
            allowed = list(visible)
        if self.scope is not None:
            allowed = [card for card in allowed if card.scope == self.scope]
        if not allowed:
            return []
        allowed_ids = {card.book_id for card in allowed}
        ordered: list[str] = []
        for card in self.bookstore.catalog_search(query, top_k=max(len(visible), 1)):
            if card.book_id in allowed_ids and card.book_id not in ordered:
                ordered.append(card.book_id)
        for card in visible:
            if card.book_id in allowed_ids and card.book_id not in ordered:
                ordered.append(card.book_id)
        return ordered[: self.max_books]

    def _candidates(self, result: dict[str, Any], allowed: Optional[list[str]]) -> list[_Candidate]:
        """Normalize LLM ``node_list`` and BM25 ``results[].node_id`` shapes, deduped and capped."""
        candidates: list[_Candidate] = []
        seen_books: set[str] = set()
        allowed_set = set(allowed) if allowed is not None else None
        for book in result.get("books") or []:
            if not isinstance(book, dict):
                continue
            book_id = book.get("book_id")
            if not isinstance(book_id, str) or book_id in seen_books:
                continue
            if allowed_set is not None and book_id not in allowed_set:
                continue
            seen_books.add(book_id)
            if len(seen_books) > self.max_books:
                break
            title = book.get("title") if isinstance(book.get("title"), str) else book_id
            scope = book.get("scope") if isinstance(book.get("scope"), str) else None
            nodes: list[tuple[str, Optional[float]]] = []
            if isinstance(book.get("node_list"), list):
                nodes = [(node_id, None) for node_id in book["node_list"] if isinstance(node_id, str)]
            elif isinstance(book.get("results"), list):
                for row in book["results"]:
                    if not isinstance(row, dict) or not isinstance(row.get("node_id"), str):
                        continue
                    score = row.get("score")
                    native = float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None
                    nodes.append((row["node_id"], native))
            seen_nodes: set[str] = set()
            for node_id, score in nodes:
                if not node_id or node_id in seen_nodes:
                    continue
                seen_nodes.add(node_id)
                candidates.append(_Candidate(book_id, title, scope, node_id, score))
                if len(seen_nodes) >= self.top_k:
                    break
        return candidates

    async def _collect(self, query: str, k: int) -> OriginSection:
        """Filter, search, read and validate one bounded origin request."""
        if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
            return self._section([], None)
        allowed = self._filtered_book_ids(query)
        if allowed is not None and not allowed:
            return self._section([], "no books match the configured scope/book_ids filter")

        if allowed is None:
            result = await self.bookstore.search(query, max_books=self.max_books, top_k=self.top_k)
        else:
            result = await self.bookstore.search(
                query, book_ids=list(allowed), max_books=self.max_books, top_k=self.top_k
            )
        candidates = self._candidates(result if isinstance(result, dict) else {}, allowed)
        diagnostics = _Diagnostics()
        if not candidates:
            return self._section([], diagnostics.note(0))

        semaphore = asyncio.Semaphore(_READ_CONCURRENCY)
        stores: dict[Path, SegmentStore] = {}

        async def bounded(candidate: _Candidate) -> list[OriginHit]:
            async with semaphore:
                return await self._evidence_for(candidate, diagnostics, stores)

        # gather() cancels every child read when this request is cancelled or times out.
        per_candidate = await asyncio.gather(*(bounded(c) for c in candidates))

        hits: list[OriginHit] = []
        seen: set[tuple[str, str, str, int, int, int]] = set()
        for group in per_candidate:
            for hit in group:
                citation = hit.metadata["citation"]
                key = (
                    hit.metadata["book_id"],
                    citation["doc_id"],
                    citation["revision"],
                    citation["seq"],
                    citation["start"],
                    citation["end"],
                )
                if key in seen:
                    continue
                seen.add(key)
                hits.append(hit)
                if len(hits) >= k:
                    break
            if len(hits) >= k:
                break
        ranked = [hit.model_copy(update={"native_rank": rank}) for rank, hit in enumerate(hits, start=1)]
        return self._section(ranked, diagnostics.note(len(ranked)))

    @staticmethod
    def _classify_failure(exc: Exception) -> str:
        """Map a per-read failure to a diagnostic bucket."""
        message = str(exc).lower()
        if "no segments" in message or "index_segments" in message:
            return "legacy"
        if "revision" in message:
            return "stale"
        return "failed"

    async def _evidence_for(
        self,
        candidate: _Candidate,
        diagnostics: _Diagnostics,
        stores: dict[Path, SegmentStore],
    ) -> list[OriginHit]:
        """Read one node and return its verified, clipped single-segment hits."""
        try:
            card, location = self.bookstore.resolve_book(candidate.book_id)
            read = await self.bookstore.read_segments(
                candidate.book_id, node_id=candidate.node_id, max_chars=self.excerpt_chars
            )
        except Exception as exc:  # partial evidence failures are counted, never fatal
            bucket = self._classify_failure(exc)
            if bucket == "legacy":
                diagnostics.legacy_books.add(candidate.book_id)
            elif bucket == "stale":
                diagnostics.stale_revisions += 1
            else:
                diagnostics.failed_reads += 1
            self.logger.debug(
                "Bookstore origin skipped %s/%s: %s", candidate.book_id, candidate.node_id, exc, exc_info=True
            )
            return []

        doc_id, revision_id = read.get("doc_id"), read.get("revision")
        tree_name = read.get("tree_name", card.tree_name)
        if not isinstance(doc_id, str) or not isinstance(revision_id, str) or tree_name != card.tree_name:
            diagnostics.stale_revisions += 1
            return []
        store_key = Path(location.trees_dir)
        store = stores.get(store_key)
        if store is None:
            store = stores[store_key] = SegmentStore(location.trees_dir)
        try:
            stored = await asyncio.to_thread(store.load_revision, tree_name, doc_id, revision_id)
        except Exception:  # noqa: BLE001 - a swept or concurrently evicted revision is simply stale
            stored = None
        if stored is None or stored.doc_id != doc_id or stored.revision != revision_id:
            diagnostics.stale_revisions += 1
            return []

        citations: list[dict[str, Any]] = []
        remaining = self.excerpt_chars
        for segment in read.get("segments") or []:
            if remaining <= 0:
                break
            citation = self._verified_citation(segment, stored, doc_id, revision_id, remaining)
            if citation is None:
                if isinstance(segment, dict) and isinstance(segment.get("text"), str) and segment["text"].strip():
                    diagnostics.invalid_excerpts += 1
                continue
            remaining -= citation["end"] - citation["start"]
            citations.append(citation)
        if not citations:
            return []

        decorated = await self.bookstore.decorate_citations(
            card, location.scope, {"generation": read.get("generation"), "citations": citations}
        )
        hits: list[OriginHit] = []
        for citation in decorated.get("citations") or []:
            hit_id = (
                f"{candidate.book_id}:{citation['doc_id']}@{citation['revision']}"
                f"#{citation['seq']}:{citation['start']}-{citation['end']}"
            )
            hits.append(
                OriginHit(
                    id=hit_id,
                    content=citation["excerpt"],
                    score=candidate.score,
                    metadata={
                        "book_id": candidate.book_id,
                        "book_title": card.title,
                        "node_id": candidate.node_id,
                        "scope": location.scope,
                        "generation": read.get("generation"),
                        "doc_id": citation["doc_id"],
                        "revision": citation["revision"],
                        "seq": citation["seq"],
                        "start": citation["start"],
                        "end": citation["end"],
                        "citation": citation,
                    },
                    origin=self.name,
                    origin_kind=self.kind,
                    native_rank=1,
                )
            )
        return hits

    @staticmethod
    def _verified_citation(
        segment: Any,
        stored: DocumentRevision,
        doc_id: str,
        revision_id: str,
        allowance: int,
    ) -> Optional[dict[str, Any]]:
        """Clip one read segment and verify it against the stored immutable revision.

        Validation uses the stored segment text at the returned address, never the
        excerpt itself: ``stored.text[start:end] == clipped`` and ``find_any_match``.
        """
        if not isinstance(segment, dict):
            return None
        text, seq, start = segment.get("text"), segment.get("seq"), segment.get("start")
        if not isinstance(text, str) or not text.strip():
            return None
        if isinstance(seq, bool) or not isinstance(seq, int) or isinstance(start, bool) or not isinstance(start, int):
            return None
        address = segment.get("address")
        if isinstance(address, dict) and (address.get("doc_id") != doc_id or address.get("revision") != revision_id):
            return None
        if seq < 0 or seq >= len(stored.segments):
            return None
        stored_segment = stored.segments[seq]
        if stored_segment.seq != seq:
            return None
        clipped = text[:allowance]
        if not clipped.strip():
            return None
        end = start + len(clipped)
        if start < 0 or end > len(stored_segment.text):
            return None
        if stored_segment.text[start:end] != clipped or not find_any_match(stored_segment.text, clipped):
            return None
        return {
            "doc_id": doc_id,
            "revision": revision_id,
            "seq": seq,
            "page": stored_segment.page,
            "ordinal": stored_segment.ordinal,
            "section": list(stored_segment.section) if stored_segment.section else stored_segment.section,
            "start": start,
            "end": end,
            "excerpt": clipped,
            "label": _segment_label(stored_segment.page, stored_segment.ordinal, stored_segment.section),
            "document": stored.source.name,
        }
