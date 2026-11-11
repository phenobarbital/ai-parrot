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
import copy
import hashlib
import itertools
import logging
import secrets
import time
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from parrot.knowledge.pageindex.content_store import NodeContentStore
from parrot.knowledge.pageindex.layout import PDFStructureError
from parrot.knowledge.pageindex.locks import TreeLockTimeout, tree_lock
from parrot.knowledge.pageindex.segments import RevisionMismatchError
from parrot.knowledge.pageindex.store import JSONTreeStore
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit, REPLACED_MARKER
from parrot.knowledge.pageindex.utils import structure_to_list

from .carding import (
    derive_toc,
    disambiguate_title,
    fallback_card_fields,
    generate_card_fields,
    sample_sections,
    slugify,
    unique_slug,
)
from .catalog import CatalogStore, merged_cards, merged_communities, merged_relations, merged_search
from .config import LibraryLocation
from .models import REL_WEIGHTS, Anchor, Annotation, BookCard, BookCommunity, BookRelation, CardDraft, RelateSummary
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

_STAGING_MARKER = "--staging-"
#: Per-scope library notebook tree (Dewey-like sectors) and the per-book notebook suffix (FEAT-876).
LIBRARY_NOTEBOOK = "_library_notes"
NOTEBOOK_SUFFIX = "_notes"
#: Relation origins recomputed by ``relate_books``; ``manual`` edges are never invalidated (S10).
_COMPUTED_RELATION_ORIGINS = ("deterministic", "llm", "community")


def notebook_tree_name(book_id: Optional[str]) -> str:
    """Tree name of a book's notebook, or of the scope's library notebook when ``book_id`` is ``None``.

    Args:
        book_id: The annotated book's id, or ``None`` for the scope-wide library notebook.

    Returns:
        ``"<book_id>_notes"`` or ``"_library_notes"``.
    """
    return LIBRARY_NOTEBOOK if book_id is None else f"{book_id}{NOTEBOOK_SUFFIX}"


_STAGING_MAX_AGE_S = 3600


def _epub_metadata_title(payload: bytes) -> str | None:
    """Read the Dublin Core title from an EPUB's OPF without full content parsing."""
    import io
    import zipfile
    from xml.etree import ElementTree

    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            container = ElementTree.fromstring(zf.read("META-INF/container.xml"))
            rootfiles = container.findall(
                ".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile"
            )
            if not rootfiles:
                return None
            opf_path = rootfiles[0].get("full-path", "")
            if not opf_path:
                return None
            opf = ElementTree.fromstring(zf.read(opf_path))
            title_el = opf.find(".//{http://purl.org/dc/elements/1.1/}title")
            if title_el is not None and title_el.text and title_el.text.strip():
                return title_el.text.strip()
    except Exception:  # noqa: BLE001
        pass
    return None


def _mobi_metadata_title(payload: bytes) -> str | None:
    """Read the book title from a MOBI file's EXTH header or full-name field."""
    try:
        if len(payload) < 132:
            return None
        num_records = int.from_bytes(payload[76:78], "big")
        if len(payload) < 78 + 8 * num_records:
            return None
        record0_offset = int.from_bytes(payload[78:82], "big")
        mobi_start = record0_offset + 16
        if len(payload) < mobi_start + 116:
            return None
        mobi_length = int.from_bytes(payload[mobi_start + 4 : mobi_start + 8], "big")
        exth_flags = int.from_bytes(payload[mobi_start + 112 : mobi_start + 116], "big")
        if exth_flags & 0x40:
            exth_offset = mobi_start + mobi_length
            if len(payload) >= exth_offset + 12 and payload[exth_offset : exth_offset + 4] == b"EXTH":
                count = int.from_bytes(payload[exth_offset + 8 : exth_offset + 12], "big")
                pos = exth_offset + 12
                for _ in range(min(count, 200)):
                    if len(payload) < pos + 8:
                        break
                    rec_type = int.from_bytes(payload[pos : pos + 4], "big")
                    rec_len = int.from_bytes(payload[pos + 4 : pos + 8], "big")
                    if rec_len < 8:
                        break
                    if rec_type == 503:
                        raw = payload[pos + 8 : pos + rec_len]
                        title = raw.decode("utf-8", errors="replace").strip()
                        if title:
                            return title
                    pos += rec_len
        if len(payload) >= mobi_start + 92:
            name_offset = int.from_bytes(payload[mobi_start + 68 : mobi_start + 72], "big")
            name_length = int.from_bytes(payload[mobi_start + 72 : mobi_start + 76], "big")
            abs_offset = record0_offset + name_offset
            if 0 < name_length <= 1024 and len(payload) >= abs_offset + name_length:
                title = payload[abs_offset : abs_offset + name_length].decode("utf-8", errors="replace").strip()
                if title:
                    return title
    except Exception:  # noqa: BLE001
        pass
    return None


def _extract_ebook_metadata_title(payload: bytes, suffix: str) -> str | None:
    """Extract the book title from EPUB/MOBI binary metadata without full content parsing."""
    suffix = suffix.lower()
    if suffix == ".epub":
        return _epub_metadata_title(payload)
    if suffix == ".mobi":
        return _mobi_metadata_title(payload)
    return None


def _is_reserved_tree_name(name: str) -> bool:
    """Identify reserved staging and replacement tree names."""
    return _STAGING_MARKER in name or REPLACED_MARKER in name


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
        *,
        reindex_lock_timeout_s: float = 5.0,
    ) -> None:
        if not locations:
            raise BookstoreError("No library locations resolved")
        if (
            isinstance(reindex_lock_timeout_s, bool)
            or not isinstance(reindex_lock_timeout_s, (int, float))
            or not 0 < reindex_lock_timeout_s < float("inf")
        ):
            raise ValueError("reindex_lock_timeout_s must be a positive finite number")
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
        self._reindex_lock_timeout_s = float(reindex_lock_timeout_s)
        self._ready_scopes: set[str] = set()
        self._ready_locks: dict[tuple[str, asyncio.AbstractEventLoop], asyncio.Lock] = {}
        self._active_staging_slugs: set[str] = set()
        self._annotation_cache: dict[tuple[str, str], tuple[tuple[int, int], dict[str, list[Annotation]]]] = {}

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
                generation_grace_s=_STAGING_MAX_AGE_S,
            )
        return self._toolkits[scope]

    async def _ready_toolkit(self, scope: str) -> PageIndexToolkit:
        """Await successful reserved-tree recovery before returning an async toolkit.

        Recovery runs once per scope per process. An interruption in ANOTHER process is only
        repaired at the next ``add_book`` (which sweeps again) or ``doctor`` run, never mid-read.
        """
        if scope in self._ready_scopes:
            return self._toolkit(scope)

        loop = asyncio.get_running_loop()
        lock = self._ready_locks.setdefault((scope, loop), asyncio.Lock())
        async with lock:
            if scope not in self._ready_scopes:
                await self._sweep_reserved_trees(scope)
                self._ready_scopes.add(scope)
        return self._toolkit(scope)

    def _operation_storage_dir(self, scope: str) -> Path:
        """Return the Bookstore-only lock namespace for one library scope."""
        return self._location(scope).root / ".bookstore-operations"

    @asynccontextmanager
    async def _book_operation_lock(
        self, scope: str, slug: str, *, timeout: Optional[float] = None
    ) -> AsyncIterator[None]:
        """Hold the separate operation lock for one book slug."""
        lock_timeout = self._reindex_lock_timeout_s if timeout is None else timeout
        async with tree_lock(self._operation_storage_dir(scope), f"book-{slug}", timeout=lock_timeout):
            yield

    @staticmethod
    def _lock_remaining(deadline: float) -> float:
        """Return the remaining duration of an operation-wide lock deadline."""
        return max(0.0, deadline - time.monotonic())

    @asynccontextmanager
    async def _operation_locks(self, locks: list[tuple[Path, str]], deadline: float) -> AsyncIterator[None]:
        """Acquire operation locks in canonical order under one deadline."""
        ordered = sorted(locks, key=lambda item: (str(item[0].resolve()), item[1]))
        async with AsyncExitStack() as stack:
            for storage_dir, name in ordered:
                await stack.enter_async_context(tree_lock(storage_dir, name, timeout=self._lock_remaining(deadline)))
            yield

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
        taken |= self._active_staging_slugs
        for loc in self.locations:
            if loc.db_path.is_file():
                taken |= self._catalog(loc.scope).taken_slugs()
            if loc.trees_dir.is_dir():
                for tree_path in loc.trees_dir.glob("*.json"):
                    stem = tree_path.stem
                    if _STAGING_MARKER in stem:
                        # An in-flight add in ANOTHER process reserves its slug only through its staging tree.
                        taken.add(stem.split(_STAGING_MARKER, maxsplit=1)[0])
                    elif not _is_reserved_tree_name(stem):
                        taken.add(stem)
        return taken

    def _staging_tree_name(self, slug: str) -> str:
        """Return a temporary tree name using an eight-hex-character suffix."""
        return f"{slug}{_STAGING_MARKER}{secrets.token_hex(4)}"

    @staticmethod
    def _scan_reserved_trees(trees_dir: Path) -> list[tuple[str, bool, float]]:
        """Blocking scan: ``(tree_name, live_tree_exists, mtime)`` for each reserved tree."""
        found: list[tuple[str, bool, float]] = []
        if not trees_dir.is_dir():
            return found
        for tree_path in trees_dir.glob("*.json"):
            name = tree_path.stem
            if not _is_reserved_tree_name(name):
                continue
            live_name = name.split(REPLACED_MARKER, maxsplit=1)[0]
            try:
                mtime = tree_path.stat().st_mtime
            except OSError:
                continue
            found.append((name, (trees_dir / f"{live_name}.json").is_file(), mtime))
        return found

    async def _sweep_reserved_trees(self, scope: str) -> None:
        """Restore interrupted swaps and sweep staging trees older than one hour."""
        location = self._location(scope)
        reserved = await asyncio.to_thread(self._scan_reserved_trees, location.trees_dir)
        if not reserved:
            return

        toolkit = self._toolkit(scope)
        for tree_name, _live_exists, _mtime in reserved:
            live_name = tree_name.split(
                REPLACED_MARKER if REPLACED_MARKER in tree_name else _STAGING_MARKER, maxsplit=1
            )[0]
            try:
                async with self._book_operation_lock(scope, live_name, timeout=0):
                    current = await asyncio.to_thread(self._scan_reserved_trees, location.trees_dir)
                    state = next((item for item in current if item[0] == tree_name), None)
                    if state is None:
                        continue
                    _name, live_exists, mtime = state
                    if REPLACED_MARKER in tree_name:
                        if not live_exists:
                            await toolkit.rename_tree(tree_name, live_name)
                        else:
                            await toolkit.delete_tree(tree_name)
                    elif _STAGING_MARKER in tree_name and time.time() - mtime > _STAGING_MAX_AGE_S:
                        await toolkit.delete_tree(tree_name)
                    if toolkit._store.exists(live_name):
                        await toolkit.vacuum_tree(live_name)
            except TreeLockTimeout:
                self.logger.debug("Skipping busy reserved tree %r during sweep", tree_name)
            except Exception:  # noqa: BLE001 — crash recovery is best-effort
                logger.warning("Failed to sweep reserved tree %r", tree_name, exc_info=True)

    async def doctor(
        self,
        scope: Optional[str] = None,
        *,
        repair: bool = False,
        relate: bool = False,
        use_llm: bool = True,
    ) -> dict[str, Any]:
        """Report recovery, structural drift and missing judgements; optionally repair or relate.

        A structural comparison only covers the derived table of contents.  It
        cannot prove that a crashed publication did not replace text with
        different content having an identical table of contents.
        """
        locations = [self._location(scope)] if scope is not None else self.locations
        report: dict[str, Any] = {
            "reserved": [],
            "books": [],
            "unjudged_book_ids": [],
            "errors": [],
        }

        for location in locations:
            reserved_before = await asyncio.to_thread(self._scan_reserved_trees, location.trees_dir)
            entries_by_name: dict[str, dict[str, Any]] = {}
            for name, live_exists, mtime in reserved_before:
                if REPLACED_MARKER in name:
                    action = "delete" if live_exists else "restore"
                    reason = "live tree exists" if live_exists else "live tree missing"
                elif time.time() - mtime > _STAGING_MAX_AGE_S:
                    action = "delete"
                    reason = "stale staging tree"
                else:
                    action = "keep"
                    reason = "active staging tree"
                entry = {"scope": location.scope, "name": name, "action": action, "reason": reason}
                report["reserved"].append(entry)
                entries_by_name[name] = entry

            try:
                await self._sweep_reserved_trees(location.scope)
            except Exception as exc:  # noqa: BLE001 — keep doctor reporting after recovery faults
                report["errors"].append({"scope": location.scope, "error": str(exc)})
            else:
                reserved_after = await asyncio.to_thread(self._scan_reserved_trees, location.trees_dir)
                remaining = {name for name, _live_exists, _mtime in reserved_after}
                for name, entry in entries_by_name.items():
                    if entry["action"] == "keep":
                        continue
                    if name not in remaining:
                        entry["action"] = "restored" if entry["action"] == "restore" else "deleted"
                        continue
                    live_name = name.split(
                        REPLACED_MARKER if REPLACED_MARKER in name else _STAGING_MARKER,
                        maxsplit=1,
                    )[0]
                    try:
                        async with self._book_operation_lock(location.scope, live_name, timeout=0):
                            entry["action"] = "error"
                            report["errors"].append(
                                {
                                    "scope": location.scope,
                                    "name": name,
                                    "error": "reserved tree remains after recovery sweep",
                                }
                            )
                    except TreeLockTimeout:
                        entry["action"] = "busy"

            toolkit = self._toolkit(location.scope)
            catalog = self._catalog(location.scope)
            for initial_card in catalog.list_cards():
                entry: dict[str, Any] = {
                    "scope": location.scope,
                    "book_id": initial_card.book_id,
                    "status": "ok",
                    "repaired": False,
                }
                report["books"].append(entry)
                try:
                    async with self._book_operation_lock(location.scope, initial_card.tree_name, timeout=0):
                        card = catalog.get(initial_card.book_id)
                        if card is None:
                            continue
                        try:
                            tree = await toolkit.get_tree(card.tree_name)
                        except (FileNotFoundError, KeyError):
                            entry["status"] = "orphan_card"
                            continue
                        toc_entries, toc_digest = derive_toc(tree)
                        if card.toc_digest == toc_digest and card.toc == toc_entries:
                            continue
                        entry["status"] = "drift"
                        if repair:
                            page_count = max(
                                (toc_entry.end_page for toc_entry in toc_entries if toc_entry.end_page is not None),
                                default=None,
                            )
                            repaired = card.model_copy(
                                update={
                                    "toc": toc_entries,
                                    "toc_digest": toc_digest,
                                    "page_count": page_count,
                                    "chapter_count": sum(1 for toc_entry in toc_entries if toc_entry.depth == 1),
                                    "source_sha256": "",
                                }
                            )
                            catalog.upsert(repaired)
                            self._invalidate_graph(card.book_id)
                            entry["repaired"] = True
                except TreeLockTimeout:
                    entry["status"] = "busy"
                except Exception as exc:  # noqa: BLE001 — each card remains independently diagnosable
                    entry["status"] = "error"
                    report["errors"].append(
                        {"scope": location.scope, "book_id": initial_card.book_id, "error": str(exc)}
                    )

        judgement_cards = (
            self.list_books()
            if scope is None
            else [card.model_copy(update={"scope": scope}) for card in self._catalog(scope).list_cards()]
        )
        unjudged = [
            card.book_id
            for card in judgement_cards
            if sum(store.judgement_count(card.book_id) for _scope, store in self._stores()) == 0
        ]
        report["unjudged_book_ids"] = unjudged
        if relate and unjudged:
            try:
                report["relate_summary"] = (await self.relate_books(unjudged, use_llm=use_llm)).model_dump()
            except Exception as exc:  # noqa: BLE001 — report relation failure without discarding diagnosis
                report["errors"].append({"error": str(exc)})
        return report

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
            if card is not None and card.kind != "notes":
                return card.model_copy(update={"scope": loc.scope}), loc
        raise BookstoreError(f"Unknown book {book_id!r} — use catalog_search/list_books first")

    def get_card(self, book_id: str) -> BookCard:
        """Full ficha for one book."""
        card, _ = self.resolve_book(book_id)
        return card

    def get_toc(self, book_id: str) -> dict[str, Any]:
        """Structured table of contents with node ids and page ranges."""
        card, loc = self.resolve_book(book_id)
        try:
            index = self._notebook_index(loc.scope, notebook_tree_name(card.book_id))
        except Exception as exc:  # noqa: BLE001 — a broken notebook must never break a book read
            logger.warning("notebook for %r unreadable: %s", card.book_id, exc)
            index = {}
        return {
            "book_id": card.book_id,
            "title": card.title,
            "toc_digest": card.toc_digest,
            "entries": [
                {**entry.model_dump(), "has_notes": bool(index.get(f"{card.book_id}#{entry.node_id}"))}
                for entry in card.toc
            ],
        }

    async def search_book(self, book_id: str, query: str, top_k: int = 8) -> list[dict[str, Any]]:
        """Hybrid search inside one book's tree.

        The LLM tree-walk runs only when an adapter is configured;
        otherwise this is BM25-only (requires the optional ``bm25s``).
        """
        card, loc = self.resolve_book(book_id)
        toolkit = await self._ready_toolkit(loc.scope)
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
        # Live generation first: a leftover legacy ``<node_id>.md`` must never be
        # served for a node id that a reindexed/renamed tree has reused.
        body = self._content_store(loc.scope).load_current(card.tree_name, node_id)
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
            "annotations": [note.model_dump() for note in self._annotations_sync(card, loc.scope, node_id)],
        }

    # ------------------------------------------------------------------
    # Notebooks (FEAT-876)
    # ------------------------------------------------------------------
    def notebook_for(self, book_id: str) -> Optional[BookCard]:
        """Registered or on-disk ``<book_id>_notes`` in the book's scope (lazy ``kind='notes'`` upsert).

        Args:
            book_id: The annotated book.

        Returns:
            The notebook card (scope stamped), or ``None`` when no notebook tree exists.
        """
        card, loc = self.resolve_book(book_id)
        return self._registered_notebook(loc.scope, notebook_tree_name(card.book_id), card)

    def library_notebook(self, scope: str) -> Optional[BookCard]:
        """Registered or on-disk ``_library_notes`` of ``scope``.

        Args:
            scope: Library scope (``"project"`` or ``"global"``).

        Returns:
            The library notebook card, or ``None`` when its tree does not exist.
        """
        return self._registered_notebook(scope, LIBRARY_NOTEBOOK, None)

    def _registered_notebook(self, scope: str, tree_name: str, book: Optional[BookCard]) -> Optional[BookCard]:
        """Return the notebook row, lazily registering an on-disk conventional tree."""
        catalog = self._catalog(scope)
        existing = catalog.get(tree_name)
        if existing is not None and existing.kind == "notes":
            return existing.model_copy(update={"scope": scope})
        if existing is not None:
            logger.warning("%r is a book, not a notebook — not registering it as notes", tree_name)
            return None
        trees = JSONTreeStore(self._location(scope).trees_dir)
        if not trees.exists(tree_name):
            return None
        card = BookCard(
            book_id=tree_name,
            title=f"Notes — {book.title}" if book is not None else f"Library notebook ({scope})",
            tree_name=tree_name,
            scope=scope,
            source_path=str(trees._path_for(tree_name)),
            source_sha256="",
            source_format="tree",
            added_at=datetime.now(timezone.utc).isoformat(),
            card_origin="fallback",
            kind="notes",
            notes_for=book.book_id if book is not None else None,
        )
        catalog.upsert(card)
        logger.info("registered notebook %r (%s)", tree_name, scope)
        return card.model_copy(update={"scope": scope})

    async def ensure_notebook(self, book_id: Optional[str], scope: str = "project") -> BookCard:
        """Create the conventional notebook tree when missing and register it.

        Args:
            book_id: Book to annotate, or ``None`` for the scope's library notebook.
            scope: Scope of the library notebook; ignored for a book notebook, which
                always lives in the book's own scope.

        Returns:
            The registered ``kind='notes'`` card.
        """
        book: Optional[BookCard] = None
        if book_id is not None:
            book, loc = self.resolve_book(book_id)
            scope = loc.scope
        name = notebook_tree_name(book.book_id if book is not None else None)
        toolkit = await self._ready_toolkit(scope)
        if not JSONTreeStore(self._location(scope).trees_dir).exists(name):
            try:
                await toolkit.create_tree(name)
            except ValueError:
                # A concurrent creator won the race; the tree exists now.
                if not JSONTreeStore(self._location(scope).trees_dir).exists(name):
                    raise
        notebook = self._registered_notebook(scope, name, book)
        if notebook is None:
            raise BookstoreError(f"Could not register notebook {name!r} in the {scope} library")
        return notebook

    def _notebook_index(self, scope: str, tree_name: str) -> dict[str, list[Annotation]]:
        """``{node_id_or_book_key: [Annotation]}`` for one notebook, cached by tree file signature.

        Keys are ``f"{book_id}#{node_id}"`` for anchors into a node and ``f"{book_id}#"`` for
        whole-book anchors. Anchors pointing into another scope are ignored (S11).
        """
        path = JSONTreeStore(self._location(scope).trees_dir)._path_for(tree_name)
        key = (scope, tree_name)
        try:
            stat = path.stat()
        except FileNotFoundError:
            self._annotation_cache.pop(key, None)
            return {}
        signature = (stat.st_mtime_ns, stat.st_size)
        cached = self._annotation_cache.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1]
        tree = JSONTreeStore(self._location(scope).trees_dir).load(tree_name)
        content = self._content_store(scope)
        index: dict[str, list[Annotation]] = {}
        for node in structure_to_list(tree.get("structure", [])):
            if not isinstance(node, dict) or not node.get("node_id"):
                continue
            metadata = node.get("metadata") or {}
            if not isinstance(metadata, dict):
                continue
            raw_anchors = metadata.get("anchors") or []
            if not isinstance(raw_anchors, list):
                logger.debug("notebook %r node %r: anchors is not a list", tree_name, node["node_id"])
                continue
            keys: list[str] = []
            for raw in raw_anchors:
                try:
                    anchor = Anchor.model_validate(raw)
                except Exception as exc:  # noqa: BLE001 — malformed anchors are reported by doctor --notes
                    logger.debug("notebook %r node %r: malformed anchor %r: %s", tree_name, node["node_id"], raw, exc)
                    continue
                if anchor.scope != scope:
                    continue
                anchor_key = f"{anchor.book_id}#{anchor.node_id or ''}"
                if anchor_key not in keys:
                    keys.append(anchor_key)
            if not keys:
                continue
            try:
                annotation = Annotation(
                    note_tree=tree_name,
                    node_id=str(node["node_id"]),
                    title=str(node.get("title") or ""),
                    body=content.load_current(tree_name, str(node["node_id"])) or "",
                    note_kind=metadata.get("note_kind", "note"),
                    origin=metadata.get("origin", "human"),
                    anchor_status=metadata.get("anchor_status", "current"),
                )
            except Exception as exc:  # noqa: BLE001 — an invalid note never hides the others
                logger.debug("notebook %r node %r: invalid annotation: %s", tree_name, node["node_id"], exc)
                continue
            for anchor_key in keys:
                index.setdefault(anchor_key, []).append(annotation)
        self._annotation_cache[key] = (signature, index)
        return index

    async def annotations_for(self, book_id: str, node_id: str) -> list[Annotation]:
        """Notes anchored to ``(book_id, node_id)``; ``[]`` when the book has no notebook.

        Args:
            book_id: The annotated book.
            node_id: Node of the book the notes point at.

        Returns:
            The anchored notebook nodes, in tree order.
        """
        card, loc = self.resolve_book(book_id)
        return self._annotations_sync(card, loc.scope, node_id)

    def _annotations_sync(self, card: BookCard, scope: str, node_id: str) -> list[Annotation]:
        """Synchronous annotation lookup used by the sync read surface."""
        try:
            index = self._notebook_index(scope, notebook_tree_name(card.book_id))
        except Exception as exc:  # noqa: BLE001 — a broken notebook must never break a book read
            logger.warning("notebook for %r unreadable: %s", card.book_id, exc)
            return []
        return list(index.get(f"{card.book_id}#{node_id}", []))

    async def _document_of(self, card: Any, toolkit: PageIndexToolkit) -> dict[str, Any]:
        """The single imported document of a book's tree."""
        documents = await toolkit.list_documents(card.tree_name)
        if not documents:
            raise BookstoreError("book has no segments — reindex it or run pageindex_index_segments")
        return documents[0]

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
        """Return per-book PageIndex evidence with generation-safe book citation labels.

        Args:
            book_id: Stable identifier of the indexed book to research.
            query: Research question for the bounded PageIndex reading loop.
            top_k: Number of first-stage candidates to consider.
            draft_answer: Whether PageIndex should ask the model for a final answer.
            budget_chars: Optional read-character budget forwarded to PageIndex.
            max_reads: Optional read-operation budget forwarded to PageIndex.
            timeout_s: Optional total request timeout forwarded to PageIndex.

        Raises:
            BookstoreError: If the book lacks indexed segments or no compatible LLM is configured.
            ValueError: If PageIndex rejects a numeric argument.
        """
        card, loc = self.resolve_book(book_id)
        if not self.has_llm:
            raise BookstoreError("agentic retrieval requires an LLM; configure a model for this bookstore")

        toolkit = await self._ready_toolkit(loc.scope)
        await self._document_of(card, toolkit)
        try:
            bundle = await toolkit.agentic_retrieve(
                card.tree_name,
                query,
                top_k=top_k,
                draft_answer=draft_answer,
                budget_chars=budget_chars,
                max_reads=max_reads,
                timeout_s=timeout_s,
            )
        except ValueError as exc:
            message = self._message(exc)
            if "requires an LLM" in message or "supports_tool_loop=False" in message:
                raise BookstoreError(message) from exc
            raise
        return await self.decorate_citations(card, loc.scope, bundle)

    async def decorate_citations(self, card: BookCard, scope: str, bundle: dict[str, Any]) -> dict[str, Any]:
        """Copy and enrich citations, using ownership only from the matching snapshot.

        Public so other packages (the multi-store origin) decorate citations identically.

        A current tree is safe to consult only when it is the same generation captured by
        the PageIndex retrieval.  It may otherwise describe a re-indexed document whose
        node ownership no longer applies to the already validated citation.
        """
        decorated = copy.deepcopy(bundle)
        decorated["book_id"] = card.book_id
        decorated["book_title"] = card.title
        expected_generation = bundle.get("generation")
        tree: Optional[dict[str, Any]] = None
        toolkit = await self._ready_toolkit(scope)
        try:
            candidate = await toolkit.get_tree(card.tree_name)
            generation = (candidate.get("generation") or {}).get("id")
            if expected_generation is not None and generation == expected_generation:
                tree = candidate
        except (KeyError, ValueError):
            self.logger.debug("Unable to load citation-decoration snapshot for %s", card.book_id, exc_info=True)

        rendered: list[str] = []
        citations = decorated.get("citations")
        if not isinstance(citations, list):
            return decorated

        for citation in citations:
            if not isinstance(citation, dict):
                continue
            section_path = self._citation_section_path(tree, citation)
            if section_path is None:
                stored = citation.get("section")
                if isinstance(stored, list) and all(isinstance(item, str) for item in stored):
                    section_path = list(stored)
            if section_path is None:
                section_path = self._toc_section_path(tree, citation)
            citation["book_id"] = card.book_id
            citation["title"] = card.title
            if section_path:
                citation["chapter"] = section_path[0]
                citation["section_path"] = section_path
            label = citation.get("label")
            if isinstance(label, str):
                chapter = citation.get("chapter")
                parts = [card.title]
                if isinstance(chapter, str) and chapter:
                    parts.append(chapter)
                parts.append(label)
                rendered.append(f"[{', '.join(parts)}]")
        decorated["rendered_citations"] = "; ".join(rendered)
        return decorated

    @staticmethod
    def _citation_section_path(tree: Optional[dict[str, Any]], citation: dict[str, Any]) -> Optional[list[str]]:
        """Return one unambiguous owning node's root-to-node titles, if available."""
        if tree is None:
            return None
        doc_id = citation.get("doc_id")
        revision = citation.get("revision")
        seq = citation.get("seq")
        if not isinstance(doc_id, str) or not isinstance(revision, str) or not isinstance(seq, int):
            return None
        matches: list[list[str]] = []

        def walk(nodes: list[dict[str, Any]], path: list[str]) -> None:
            for node in nodes:
                title = node.get("title")
                node_path = path + [title] if isinstance(title, str) and title else path
                if node.get("doc_id") == doc_id and node.get("revision") == revision:
                    for owned in node.get("owned") or []:
                        if isinstance(owned, list) and len(owned) == 2 and owned[0] <= seq < owned[1]:
                            matches.append(node_path)
                            break
                children = node.get("nodes") or []
                if isinstance(children, list):
                    walk(children, node_path)

        structure = tree.get("structure") or []
        if isinstance(structure, list):
            walk(structure, [])
        return matches[0] if len(matches) == 1 and matches[0] else None

    @staticmethod
    def _toc_section_path(tree: Optional[dict[str, Any]], citation: dict[str, Any]) -> Optional[list[str]]:
        """Return a matching snapshot's unique top-level page chapter, if any."""
        if tree is None or not isinstance(citation.get("page"), int):
            return None
        page = citation["page"]
        matches: list[str] = []
        for node in tree.get("structure") or []:
            start, end, title = node.get("start_index"), node.get("end_index"), node.get("title")
            if isinstance(start, int) and isinstance(end, int) and isinstance(title, str) and start <= page <= end:
                matches.append(title)
        return [matches[0]] if len(matches) == 1 else None

    @staticmethod
    def _book_result(card: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"book_id": card.book_id, "book_title": card.title, **result}

    @staticmethod
    def _message(exc: Exception) -> str:
        return str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)

    async def read_pages(
        self, book_id: str, pages: str, max_chars: int = 12000, cursor: Optional[str] = None
    ) -> dict[str, Any]:
        """Read a page range of a book (``"5-7,12"``) with citable segment addresses."""
        card, loc = self.resolve_book(book_id)
        toolkit = await self._ready_toolkit(loc.scope)
        doc = await self._document_of(card, toolkit)
        try:
            result = await toolkit.read_pages(card.tree_name, doc["doc_id"], pages, max_chars=max_chars, cursor=cursor)
        except (KeyError, ValueError) as exc:
            raise BookstoreError(self._message(exc)) from exc
        return self._book_result(card, result)

    async def read_segments(
        self,
        book_id: str,
        start: Optional[int] = None,
        end: Optional[int] = None,
        node_id: Optional[str] = None,
        max_chars: int = 12000,
        cursor: Optional[str] = None,
        *,
        expected_revision: Optional[str] = None,
    ) -> dict[str, Any]:
        """Read paragraphs of a book by position or a section's own text (``node_id``).

        Args:
            book_id: Stable identifier of the book to read.
            start: Optional first segment sequence number.
            end: Optional exclusive final segment sequence number.
            node_id: Optional section node to read instead of a sequence range.
            max_chars: Maximum text budget for the read.
            cursor: Optional continuation cursor from a previous read.
            expected_revision: Optional revision that the returned snapshot must match.

        Raises:
            RevisionMismatchError: The returned snapshot or cursor names another revision.
            BookstoreError: The underlying read cannot be completed.
        """
        card, loc = self.resolve_book(book_id)
        toolkit = await self._ready_toolkit(loc.scope)
        doc = await self._document_of(card, toolkit)
        try:
            result = await toolkit.read_segments(
                card.tree_name,
                doc["doc_id"],
                start=start,
                end=end,
                node_id=node_id,
                max_chars=max_chars,
                cursor=cursor,
            )
        except RevisionMismatchError:
            raise
        except (KeyError, ValueError) as exc:
            raise BookstoreError(self._message(exc)) from exc
        if expected_revision is not None and result["revision"] != expected_revision:
            raise RevisionMismatchError(f"Expected revision {expected_revision!r}, received {result['revision']!r}")
        return self._book_result(card, result)

    async def outline(self, book_id: str, node_id: Optional[str] = None, max_depth: int = 3) -> dict[str, Any]:
        """Compact outline of a book or one of its sections."""
        card, loc = self.resolve_book(book_id)
        toolkit = await self._ready_toolkit(loc.scope)
        await self._document_of(card, toolkit)
        try:
            result = await toolkit.outline(card.tree_name, node_id=node_id, max_depth=max_depth)
        except (KeyError, ValueError) as exc:
            raise BookstoreError(self._message(exc)) from exc
        return self._book_result(card, result)

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
                toolkit = await self._ready_toolkit(scope)
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
                already catalogued. A file whose content changed at an
                already-catalogued path is always re-indexed in place
                (same ``book_id``), ``force`` or not.
            relate: When ``True``, run :meth:`relate_books` for just
                this book (Stages 1-2 only, no communities) right after
                cataloguing it. ``False`` by default (G3: plain ``add``
                must never call the relation LLM).

        Returns:
            ``(card, status)`` where status is ``"added"``, ``"updated"``
            or ``"skipped"`` (sha match without ``force``). ``"updated"``
            also covers changed content at an already-catalogued path.

        Raises:
            BookstoreError: Unsupported format, missing file, ``.pdf``
                or ``.txt`` without an LLM, or EPUB without
                ``ai-parrot-loaders``.
        """
        path = await asyncio.to_thread(lambda: Path(file_path).expanduser().resolve())
        if not await asyncio.to_thread(path.is_file):
            raise BookstoreError(f"File not found: {path}")
        fmt = _FORMAT_BY_SUFFIX.get(path.suffix.lower())
        if fmt is None:
            raise BookstoreError(f"Unsupported format {path.suffix!r} — " f"supported: {sorted(_FORMAT_BY_SUFFIX)}")

        toolkit = await self._ready_toolkit(scope)
        catalog = self._catalog(scope)
        await self._sweep_reserved_trees(scope)
        payload = await asyncio.to_thread(path.read_bytes)
        sha256 = hashlib.sha256(payload).hexdigest()
        ebook_metadata_title: str | None = None
        if fmt in ("epub", "mobi"):
            ebook_metadata_title = await asyncio.to_thread(
                _extract_ebook_metadata_title, payload, path.suffix
            )
        deadline = time.monotonic() + self._reindex_lock_timeout_s
        source_locks = [
            (self._operation_storage_dir(scope), f"path-{hashlib.sha256(str(path).encode()).hexdigest()}"),
            (self._operation_storage_dir(scope), f"sha-{sha256}"),
        ]

        def identity() -> tuple[Optional[BookCard], bool]:
            """Resolve source identity from the catalog while source locks are held."""
            by_sha = catalog.find_by_sha(sha256)
            return by_sha or catalog.find_by_path(str(path)), by_sha is not None

        async def ingest(
            existing: Optional[BookCard],
            status: str,
            slug: str,
            *,
            after_staging: Optional[Callable[[], Awaitable[None]]] = None,
        ) -> tuple[BookCard, str]:
            """Build, publish and catalog one book while source/book locks are held."""
            staging = self._staging_tree_name(slug)
            doc_description = ""
            self._active_staging_slugs.add(slug)
            try:
                await toolkit.create_tree(staging, doc_name=title or ebook_metadata_title or path.stem)
                if after_staging is not None:
                    await after_staging()
                if fmt == "pdf":
                    try:
                        result = await toolkit.import_pdf(
                            tree_name=staging,
                            pdf_path=str(path),
                            with_summaries=self.has_llm,
                            with_doc_description=self.has_llm,
                            structure_mode="auto" if self.has_llm else "layout",
                        )
                    except PDFStructureError as exc:
                        raise BookstoreError(f"Cannot index {path.name}: {exc}") from exc
                    doc_description = result.get("doc_description") or ""
                elif fmt == "md":
                    await toolkit.insert_markdown(
                        tree_name=staging,
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
                        tree_name=staging,
                        content=await asyncio.to_thread(path.read_text, encoding="utf-8"),
                    )
                elif fmt == "docx":
                    markdown = await self._docx_to_markdown(path)
                    await toolkit.insert_markdown(
                        tree_name=staging,
                        markdown=markdown,
                        doc_name=title or path.stem,
                    )
                else:  # ebook
                    sections = await self._ebook_sections(path)
                    await toolkit.insert_ebook(
                        tree_name=staging,
                        sections=sections,
                    )
                tree = await toolkit.get_tree(staging)
                toc_entries, toc_digest = derive_toc(tree)
                draft = await self._draft_card(
                    path=path,
                    tree_name=staging,
                    scope=scope,
                    doc_description=doc_description or tree.get("doc_description") or "",
                    toc_digest=toc_digest,
                    toc_entries=toc_entries,
                    tree=tree,
                    metadata_title=ebook_metadata_title,
                )
                if not title:
                    taken_titles = {c.title.casefold() for c in self.list_books() if c.book_id != slug}
                    final_title = disambiguate_title(draft.title, taken_titles, toc_entries=toc_entries, stem=path.stem)
                else:
                    final_title = title
                card_origin = "fallback" if not self.has_llm else "llm"
                if title or authors or topics:
                    card_origin = "manual"
                # An in-place re-index of a manually edited card (``update_card`` /
                # explicit overrides at a previous ``add``) must not silently revert
                # those edits to the fresh draft: keep title/authors/topics/summary
                # unless this call overrides them explicitly.
                preserved = (
                    existing
                    if existing is not None and status == "updated" and existing.card_origin == "manual"
                    else None
                )
                if preserved is not None:
                    if not title:
                        final_title = preserved.title
                    card_origin = "manual"

                page_count = max(
                    (e.end_page for e in toc_entries if e.end_page is not None),
                    default=None,
                )
                card = BookCard(
                    book_id=slug,
                    title=final_title,
                    authors=authors if authors is not None else (preserved.authors if preserved else draft.authors),
                    year=draft.year,
                    language=draft.language,
                    topics=topics if topics is not None else (preserved.topics if preserved else draft.topics),
                    summary=preserved.summary if preserved and preserved.summary else draft.summary,
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
                await toolkit.rename_tree(staging, slug, overwrite=status == "updated")
            except BaseException:  # noqa: BLE001 — includes CancelledError so a cancelled ingest cleans up
                # Never leave a half-imported staging tree behind an errored or cancelled add.
                try:
                    await toolkit.delete_tree(staging)
                except Exception:  # noqa: BLE001 — best-effort cleanup
                    logger.debug("Cleanup of tree %r failed", staging, exc_info=True)
                raise
            finally:
                self._active_staging_slugs.discard(slug)

            preserve_graph = (
                status == "updated"
                and existing is not None
                and bool(existing.source_sha256)
                and existing.source_sha256 == sha256
                and existing.toc_digest == toc_digest
            )
            if preserve_graph:
                card = card.model_copy(
                    update={
                        "community_id": existing.community_id,
                        "community_label": existing.community_label,
                    }
                )
            self._content_stores.pop(scope, None)
            catalog.upsert(card)
            if status == "updated" and not preserve_graph:
                self._invalidate_graph(slug)
            return card, status

        try:
            async with self._operation_locks(source_locks, deadline):
                while True:
                    existing, _same_bytes = identity()
                    if existing is not None:
                        slug = existing.book_id
                        async with self._operation_locks(
                            [(self._operation_storage_dir(scope), f"book-{slug}")], deadline
                        ):
                            refreshed, refreshed_same_bytes = identity()
                            if refreshed is None or refreshed.book_id != slug:
                                continue
                            if refreshed_same_bytes and not force:
                                return refreshed.model_copy(update={"scope": scope}), "skipped"
                            card, status = await ingest(refreshed, "updated", slug)
                            break

                    own_storage_dir = self._operation_storage_dir(scope)
                    allocation_locks = [
                        (location.root / ".bookstore-operations", "allocation")
                        for location in self.locations
                        if location.scope == scope or location.root.exists()
                    ]
                    async with AsyncExitStack() as allocations:
                        for storage_dir, name in sorted(
                            allocation_locks, key=lambda item: (str(item[0].resolve()), item[1])
                        ):
                            try:
                                await allocations.enter_async_context(
                                    tree_lock(storage_dir, name, timeout=self._lock_remaining(deadline))
                                )
                            except TreeLockTimeout:
                                raise
                            except OSError:
                                # A location this call cannot write to (read-only global library) cannot
                                # receive a concurrent add either, so there is nothing to serialize against.
                                if storage_dir == own_storage_dir:
                                    raise
                                self.logger.debug("Skipping allocation lock for read-only %s", storage_dir)
                        refreshed, _ = identity()
                        if refreshed is not None:
                            continue
                        slug = unique_slug(slugify(title or ebook_metadata_title or path.stem), self._all_taken_slugs())
                        async with self._operation_locks(
                            [(self._operation_storage_dir(scope), f"book-{slug}")], deadline
                        ):
                            refreshed, _ = identity()
                            if refreshed is not None or slug in self._all_taken_slugs():
                                continue

                            async def release_allocation() -> None:
                                """Release global slug allocation after the staging name is reserved."""
                                await allocations.aclose()

                            card, status = await ingest(None, "added", slug, after_staging=release_allocation)
                            break
        except TreeLockTimeout as exc:
            raise BookstoreError(f"Re-index already in progress for source {path} or its book") from exc

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
        tree: dict,
        metadata_title: str | None = None,
    ) -> CardDraft:
        if not self.has_llm:
            return fallback_card_fields(path, toc_entries, metadata_title=metadata_title)
        # Pinned to ``tree``: ids resolve via load_node (body_ref first), so a
        # stale <node_id>.md left by an overwrite can never be sampled instead
        # of the live body.
        loader = self._content_store(scope).loader_for(tree_name, tree)
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
            return fallback_card_fields(path, toc_entries, metadata_title=metadata_title)

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
            force: Re-index files already catalogued (by sha256). Files
                whose content changed at a catalogued path are always
                re-indexed in place.
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
        folder_resolved = await asyncio.to_thread(lambda: Path(folder).expanduser().resolve())
        return {
            "folder": str(folder_resolved),
            "results": results,
            "ignored": [str(p) for p in ignored],
        }

    def _invalidate_graph(self, book_id: str) -> None:
        """Drop every relation/judgement touching ``book_id`` and clear the community partition.

        Edges touching ``book_id`` may live in either scope's DB (the scope
        owning an edge's ``src``), so the cascade runs across every store.
        Community ids are membership hashes, so any change to a member
        invalidates the whole partition; the next ``relate_books`` recomputes it.
        """
        for _scope, store in self._stores():
            for origin in _COMPUTED_RELATION_ORIGINS:
                store.delete_relations(book_id=book_id, origin=origin)
            store.delete_judgements(book_id)
        self._clear_communities()

    async def remove_book(self, book_id: str, *, with_notes: bool = False) -> bool:
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

        The book's notebook (``<book_id>_notes``) is kept by default as an
        orphan (row kept, ``notes_for`` cleared); ``with_notes=True`` also
        deletes the notebook tree and its row.

        Args:
            book_id: The book to remove.
            with_notes: Also delete the book's notebook.

        Returns:
            Whether the catalog row was removed.
        """
        card, loc = self.resolve_book(book_id)
        toolkit = await self._ready_toolkit(loc.scope)
        try:
            async with self._book_operation_lock(loc.scope, card.tree_name):
                try:
                    await toolkit.delete_tree(card.tree_name)
                except Exception:  # noqa: BLE001 — the tree may already be gone
                    logger.warning("Tree %r missing while removing book %r", card.tree_name, book_id)
                catalog = self._catalog(loc.scope)
                notebook = self._registered_notebook(loc.scope, notebook_tree_name(card.book_id), card)
                removed = catalog.remove(book_id)
                if notebook is not None:
                    if with_notes:
                        try:
                            await toolkit.delete_tree(notebook.tree_name)
                        except Exception:  # noqa: BLE001 — the notebook tree may already be gone
                            logger.warning("Notebook tree %r missing while removing %r", notebook.tree_name, book_id)
                        catalog.remove(notebook.book_id)
                        self._annotation_cache.pop((loc.scope, notebook.tree_name), None)
                    else:
                        catalog.upsert(notebook.model_copy(update={"notes_for": None}))
                self._invalidate_graph(book_id)
        except TreeLockTimeout as exc:
            raise BookstoreError(f"Re-index already in progress for {card.tree_name!r}") from exc
        return removed

    async def optimize_book(
        self,
        book_id: str,
        *,
        apply: bool = False,
        llm_passes: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Optimize a book's PageIndex tree and refresh its structural card fields.

        Args:
            book_id: Catalog id of the book whose tree should be optimized.
            apply: Whether to publish the optimized tree. Defaults to a dry run.
            llm_passes: Whether to run model-backed optimizer passes. When omitted,
                follows whether this bookstore has an LLM adapter configured.

        Returns:
            The optimizer report.
        """
        card, loc = self.resolve_book(book_id)
        toolkit = await self._ready_toolkit(loc.scope)

        async def run_optimization() -> dict[str, Any]:
            """Run the optimizer and persist structural fields after publication."""
            report = await toolkit.optimize(
                card.tree_name,
                apply=apply,
                llm_passes=self.has_llm if llm_passes is None else llm_passes,
            )
            if apply and not report.get("errors"):
                tree = await toolkit.get_tree(card.tree_name)
                toc_entries, toc_digest = derive_toc(tree)
                page_count = max(
                    (entry.end_page for entry in toc_entries if entry.end_page is not None),
                    default=None,
                )
                updated = card.model_copy(
                    update={
                        "toc": toc_entries,
                        "toc_digest": toc_digest,
                        "chapter_count": sum(1 for entry in toc_entries if entry.depth == 1),
                        "page_count": page_count,
                    }
                )
                self._catalog(loc.scope).upsert(updated)
            return report

        if not apply:
            return await run_optimization()
        try:
            async with self._book_operation_lock(loc.scope, card.tree_name):
                return await run_optimization()
        except TreeLockTimeout as exc:
            raise BookstoreError(f"Re-index already in progress for {card.tree_name!r}") from exc

    async def refresh_card(self, book_id: str) -> BookCard:
        """Re-run carding on an existing tree (e.g. after enabling an LLM)."""
        card, loc = self.resolve_book(book_id)
        tree = await (await self._ready_toolkit(loc.scope)).get_tree(card.tree_name)
        toc_entries, toc_digest = derive_toc(tree)
        draft = await self._draft_card(
            path=Path(card.source_path),
            tree_name=card.tree_name,
            scope=loc.scope,
            doc_description=tree.get("doc_description") or "",
            toc_digest=toc_digest,
            toc_entries=toc_entries,
            tree=tree,
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

    def update_card(
        self,
        book_id: str,
        *,
        title: Optional[str] = None,
        authors: Optional[list[str]] = None,
        topics: Optional[list[str]] = None,
        summary: Optional[str] = None,
    ) -> BookCard:
        """Overwrite the given descriptive fields of an existing card and persist it.

        Only non-``None`` arguments are applied. ``title``/``summary`` are
        stripped; an empty ``title`` is rejected. Marks the card
        ``card_origin="manual"``; community stamps survive untouched.

        Raises:
            BookstoreError: Unknown ``book_id``, empty ``title``, or no field given.
        """
        if title is None and authors is None and topics is None and summary is None:
            raise BookstoreError("Nothing to update — pass title, authors, topics or summary")
        card, loc = self.resolve_book(book_id)
        changes: dict[str, Any] = {"card_origin": "manual"}
        if title is not None:
            title = title.strip()
            if not title:
                raise BookstoreError("title must not be empty")
            changes["title"] = title
        if authors is not None:
            changes["authors"] = list(authors)
        if topics is not None:
            changes["topics"] = list(topics)
        if summary is not None:
            changes["summary"] = summary.strip()
        updated = card.model_copy(update=changes)
        self._catalog(loc.scope).upsert(updated)
        logger.info("update_card: %s (%s)", book_id, ", ".join(k for k in changes if k != "card_origin"))
        return updated
