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
from .catalog import CatalogStore, merged_cards, merged_search
from .config import LibraryLocation
from .models import BookCard, CardDraft

logger = logging.getLogger(__name__)

_FORMAT_BY_SUFFIX = {
    ".pdf": "pdf",
    ".md": "md",
    ".markdown": "md",
    ".txt": "txt",
    ".epub": "epub",
    # .doc (legacy binary) is deliberately absent: python-docx can't read it.
    ".docx": "docx",
}


class BookstoreError(RuntimeError):
    """User-facing bookstore failure (bad input, missing book, no LLM…)."""


class _NullAdapter:
    """Adapter stand-in when no LLM is configured.

    Exposes the two attributes :class:`PageIndexToolkit` dereferences at
    construction time (``model``, ``client``). ``ask()`` degrades to an
    empty answer so LLM-optional ingest passes (per-node summaries in
    ``md_to_tree``) simply produce no summaries instead of failing the
    whole import; ``ask_structured()`` raises because its callers
    (two-step text ingest, carding) cannot proceed without a model —
    :class:`Bookstore` guards those paths up front.
    """

    model: Optional[str] = None
    client: Optional[Any] = None

    async def ask(self, *args: Any, **kwargs: Any) -> str:
        return ""

    async def ask_structured(self, *args: Any, **kwargs: Any) -> Any:
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
            self._content_stores[scope] = NodeContentStore(
                self._location(scope).trees_dir
            )
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
        raise BookstoreError(
            f"Unknown book {book_id!r} — use catalog_search/list_books first"
        )

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

    async def search_book(
        self, book_id: str, query: str, top_k: int = 8
    ) -> list[dict[str, Any]]:
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
            raise BookstoreError(
                f"Unknown section {node_id!r} in book {book_id!r} — "
                "check bookstore_get_toc"
            )
        return {
            "book_id": card.book_id,
            "book_title": card.title,
            "node_id": node_id,
            "title": entry.title if entry else None,
            "start_page": entry.start_page if entry else None,
            "end_page": entry.end_page if entry else None,
            "content": body or "",
        }

    async def search(
        self,
        query: str,
        book_ids: Optional[list[str]] = None,
        max_books: int = 3,
        top_k: int = 5,
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
                            **{
                                k: v
                                for k, v in result.items()
                                if k != "tree_name"
                            },
                        }
                    )
        else:
            for card in cards:
                results = await self.search_book(
                    card.book_id, query, top_k=top_k
                )
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
    ) -> tuple[BookCard, str]:
        """Index a book file and catalog its ficha.

        Args:
            file_path: Source ``.pdf`` / ``.md`` / ``.txt`` / ``.epub``.
            scope: Target library (``"project"`` or ``"global"``).
            title: Override the carded title (also seeds the slug).
            authors: Override the carded authors.
            topics: Override the carded topics.
            force: Re-index even when the same file (by sha256) is
                already catalogued.

        Returns:
            ``(card, status)`` where status is ``"added"``, ``"updated"``
            or ``"skipped"`` (sha match without ``force``).

        Raises:
            BookstoreError: Unsupported format, missing file, ``.txt``
                without an LLM, or EPUB without ``ai-parrot-loaders``.
        """
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            raise BookstoreError(f"File not found: {path}")
        fmt = _FORMAT_BY_SUFFIX.get(path.suffix.lower())
        if fmt is None:
            raise BookstoreError(
                f"Unsupported format {path.suffix!r} — "
                f"supported: {sorted(_FORMAT_BY_SUFFIX)}"
            )

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
                    markdown=await asyncio.to_thread(
                        path.read_text, encoding="utf-8"
                    ),
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
                    content=await asyncio.to_thread(
                        path.read_text, encoding="utf-8"
                    ),
                )
            elif fmt == "docx":
                markdown = await self._docx_to_markdown(path)
                await toolkit.insert_markdown(
                    tree_name=slug,
                    markdown=markdown,
                    doc_name=title or path.stem,
                )
            else:  # epub
                markdown = await self._epub_to_markdown(path)
                await toolkit.insert_markdown(
                    tree_name=slug,
                    markdown=markdown,
                    doc_name=title or path.stem,
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
        )
        catalog.upsert(card)
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
        """Convert a Word document to markdown via parrot_loaders.

        Reuses ``MSWordLoader.docx_to_markdown`` (heading styles →
        markdown headings, tables → markdown tables). Lazy import —
        ``ai-parrot-loaders`` is a separate distribution and core must
        not hard-depend on it. A document with no Word heading styles
        yields heading-less markdown and therefore a 0-chapter tree
        (same accepted behavior as the markdown route).
        """
        try:
            from parrot_loaders.docx import MSWordLoader
        except ImportError as exc:
            raise BookstoreError(
                "DOCX support requires the ai-parrot-loaders package "
                "(pip install ai-parrot-loaders)"
            ) from exc
        loader = MSWordLoader(str(path))
        markdown = await asyncio.to_thread(loader.docx_to_markdown, path)
        if not (markdown or "").strip():
            raise BookstoreError(f"No readable content found in {path.name}")
        return markdown

    async def _epub_to_markdown(self, path: Path) -> str:
        """Convert an EPUB to one markdown document via parrot_loaders.

        Lazy import — ``ai-parrot-loaders`` is a separate distribution
        and core must not hard-depend on it.
        """
        try:
            from parrot_loaders.epubloader import EpubLoader
        except ImportError as exc:
            raise BookstoreError(
                "EPUB support requires the ai-parrot-loaders package "
                "(pip install ai-parrot-loaders)"
            ) from exc
        loader = EpubLoader(
            str(path),
            as_markdown=True,
            per_chapter=True,
            include_toc_document=False,
        )
        documents = await loader.load(split_documents=False)
        documents.sort(
            key=lambda d: d.metadata.get("section_order") or 0
        )
        parts: list[str] = []
        for doc in documents:
            chapter_title = doc.metadata.get("section_title") or "Chapter"
            parts.append(f"## {chapter_title}\n\n{doc.page_content}")
        if not parts:
            raise BookstoreError(f"No readable chapters found in {path.name}")
        book_title = path.stem.replace("_", " ").replace("-", " ").title()
        return f"# {book_title}\n\n" + "\n\n".join(parts)

    @staticmethod
    def iter_folder_files(
        folder: str | Path, recursive: bool = False
    ) -> tuple[list[Path], list[Path]]:
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

        Returns:
            ``{"folder", "results": [{file, status, book_id?, error?}],
            "ignored": [paths]}`` where status is ``added`` /
            ``updated`` / ``skipped`` / ``failed``.
        """
        supported, ignored = self.iter_folder_files(folder, recursive=recursive)
        results: list[dict[str, Any]] = []
        for path in supported:
            try:
                card, status = await self.add_book(
                    path, scope=scope, force=force
                )
                results.append(
                    {"file": str(path), "status": status, "book_id": card.book_id}
                )
            except Exception as exc:  # noqa: BLE001 — keep the loop alive
                logger.warning("Failed to ingest %s: %s", path, exc)
                results.append(
                    {"file": str(path), "status": "failed", "error": str(exc)}
                )
        return {
            "folder": str(Path(folder).expanduser().resolve()),
            "results": results,
            "ignored": [str(p) for p in ignored],
        }

    async def remove_book(self, book_id: str) -> bool:
        """Remove a book — catalog row plus its PageIndex tree."""
        card, loc = self.resolve_book(book_id)
        toolkit = self._toolkit(loc.scope)
        try:
            await toolkit.delete_tree(card.tree_name)
        except Exception:  # noqa: BLE001 — the tree may already be gone
            logger.warning(
                "Tree %r missing while removing book %r", card.tree_name, book_id
            )
        return self._catalog(loc.scope).remove(book_id)

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
            }
        )
        self._catalog(loc.scope).upsert(updated)
        return updated
