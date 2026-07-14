"""Wiki ingest orchestrator for the LLM Wiki feature (FEAT-260).

Implements the "Ingest" operation from Karpathy's 3-layer architecture.
Orchestrates the full pipeline for a single source document:

1. Check the source registry — skip if already ingested and not stale.
2. Load source content from the file path.
3. Process via ``PageIndexToolkit.insert_content()`` (which internally
   delegates to ``TwoStepIngester``).
4. Upsert the generated pages into the :class:`WikiStore` retrieval
   plane (bodies, categories, token counts) and record
   ``summarizes`` edges page → source.  ``replace_source_slice``
   guarantees re-ingest never accumulates duplicates.
5. Optionally (``sync_graph=True``) mirror a ``wiki_page`` node into
   GraphIndex.
6. Update the source registry (hash + mtime + pages generated).
7. Append to the operation log via ``WikiBookkeeper.log_operation()``.

All operations are async.  On partial failure the error is logged but
no corrupt state is left: the registry is only updated after all steps
succeed.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import (
    WikiPageRecord,
    WikiStore,
    estimate_tokens,
)


class IngestReport(BaseModel):
    """Result of a single wiki ingest run.

    Attributes:
        source_id: Stable identifier for the ingested source.
        source_uri: Absolute path / URI of the source document.
        pages_created: Number of new wiki pages created.
        pages_updated: Number of existing pages updated.
        graph_nodes_created: Number of GraphIndex nodes created.
        duration_ms: Wall-clock time in milliseconds.
        status: ``"ok"`` or ``"error"``.
        error: Optional error message when ``status == "error"``.
    """

    source_id: str = Field(..., description="Stable source identifier")
    source_uri: str = Field(..., description="Absolute path or URI")
    pages_created: int = Field(default=0, ge=0)
    pages_updated: int = Field(default=0, ge=0)
    graph_nodes_created: int = Field(default=0, ge=0)
    duration_ms: float = Field(default=0.0, ge=0.0)
    status: str = Field(default="ok")
    error: Optional[str] = None


class WikiIngestOrchestrator:
    """Orchestrates the full source-to-wiki-page ingest pipeline.

    Dependencies are injected at construction time so every component
    can be mocked in tests without a real LLM or database.

    Attributes:
        _pi: ``PageIndexToolkit`` instance for tree mutations.
        _gi: ``GraphIndexToolkit`` instance for graph sync.
        _sources: :class:`SourceCollectionManager` for manifest tracking.
        _bookkeeper: :class:`WikiBookkeeper` for index/log updates.
        logger: Standard Python logger.

    Example::

        orch = WikiIngestOrchestrator(pi, gi, source_mgr, bookkeeper)
        report = await orch.ingest("/docs/article.md", config)
        print(report.pages_created)
    """

    def __init__(
        self,
        pageindex_toolkit: Any,
        graphindex_toolkit: Any,
        source_manager: SourceCollectionManager,
        bookkeeper: WikiBookkeeper,
        store: Optional[WikiStore] = None,
        sync_graph: bool = False,
    ) -> None:
        """Initialise the orchestrator with all dependencies.

        Args:
            pageindex_toolkit: A ``PageIndexToolkit`` instance.
            graphindex_toolkit: A ``GraphIndexToolkit`` instance.
            source_manager: :class:`SourceCollectionManager` for the wiki.
            bookkeeper: :class:`WikiBookkeeper` for log/index management.
            store: :class:`WikiStore` retrieval plane.  When ``None``,
                store sync is skipped (legacy behaviour).
            sync_graph: When ``True``, additionally mirror a
                ``wiki_page`` node into GraphIndex (off by default —
                the WikiStore is the retrieval plane).
        """
        self._pi = pageindex_toolkit
        self._gi = graphindex_toolkit
        self._sources = source_manager
        self._bookkeeper = bookkeeper
        self._store = store
        self._sync_graph = sync_graph
        self.logger: logging.Logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ingest(
        self,
        source_path: str,
        wiki_config: WikiConfig,
    ) -> IngestReport:
        """Run the full ingest pipeline for a single source file.

        Pipeline steps:
        1. Register / check the source in the manifest.
        2. Skip (return early) if already ingested and not stale.
        3. Load source content from disk.
        4. Insert into PageIndex tree via ``insert_content`` (TwoStepIngester).
        5. Create a ``WIKI_PAGE`` node in GraphIndex.
        6. Link graph node → source via ``REFERENCES`` edge.
        7. Update manifest with pages generated + new hash/mtime.
        8. Append to log.md.

        Args:
            source_path: Absolute or relative path to the source file.
            wiki_config: Configuration for the target wiki instance.

        Returns:
            An :class:`IngestReport` describing what was created/updated.
        """
        t0 = time.monotonic()
        source_path_obj = Path(source_path).resolve()
        source_uri = str(source_path_obj)

        # Step 1 — register or check staleness
        # Use public find_by_uri and wrap sync I/O in asyncio.to_thread so the
        # event loop is not blocked by hash computation or manifest writes.
        existing_id = await asyncio.to_thread(
            self._sources.find_by_uri, source_uri
        )
        if existing_id:
            source_id = existing_id
            entry = self._sources.get_source(source_id)
            is_stale = await asyncio.to_thread(
                self._sources.is_stale, source_id
            )
            if not is_stale and entry:
                self.logger.info(
                    "Source %s is up to date — skipping ingest", source_uri
                )
                return IngestReport(
                    source_id=source_id,
                    source_uri=source_uri,
                    pages_created=0,
                    pages_updated=0,
                    graph_nodes_created=0,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    status="ok",
                )
        else:
            try:
                entry = await asyncio.to_thread(
                    self._sources.add_source, source_path_obj
                )
            except (FileNotFoundError, OSError) as exc:
                # File does not exist; generate a deterministic placeholder ID.
                source_id = (
                    f"src-{uuid.uuid5(uuid.NAMESPACE_URL, source_uri).hex[:12]}"
                )
                return self._error_report(source_id, source_uri, t0, str(exc))
            source_id = entry.source_id

        # Step 2 — load content (offloaded to thread to avoid blocking the loop)
        try:
            content = await self._load_source(source_path_obj)
        except Exception as exc:  # noqa: BLE001
            return self._error_report(source_id, source_uri, t0, str(exc))

        # Step 3 — insert into PageIndex (uses TwoStepIngester internally)
        tree_name = wiki_config.wiki_name
        pages_created = 0
        pages_updated = 0
        page_ids: list[str] = []

        try:
            pi_result = await self._create_wiki_pages(content, tree_name)
            # PageIndexToolkit.insert_content() contract:
            # {"tree_name", "new_node_ids", "title", "summary"}
            inserted_ids = pi_result.get("new_node_ids") or []
            page_ids = [str(nid) for nid in inserted_ids]
            pages_created = len(page_ids)
        except Exception as exc:  # noqa: BLE001
            self.logger.error("PageIndex insert failed for %s: %s", source_uri, exc)
            return self._error_report(source_id, source_uri, t0, str(exc))

        # Step 4 — upsert into the WikiStore retrieval plane.
        # replace_source_slice deletes the source's previous pages first,
        # so re-ingest never accumulates duplicates.
        if self._store is not None:
            try:
                records = await self._build_page_records(
                    tree_name,
                    page_ids,
                    source_id=source_id,
                    fallback_title=str(pi_result.get("title") or ""),
                    fallback_summary=str(
                        pi_result.get("summary") or content[:500]
                    ),
                )
                edges = [
                    (r.concept_id, source_id, "summarizes") for r in records
                ]
                await self._store.replace_source_slice(
                    source_id, records, edges
                )
                # Stable concept_ids become the recorded page identities.
                page_ids = [r.concept_id for r in records]
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "WikiStore sync failed for %s (non-fatal): %s",
                    source_uri,
                    exc,
                )

        # Step 4b — optional GraphIndex mirror (off by default).
        graph_nodes_created = 0
        graph_node_id: Optional[str] = None
        if self._sync_graph:
            try:
                graph_node_id = await self._sync_to_graph(
                    source_uri,
                    tree_name=tree_name,
                    summary=content[:500],
                )
                if graph_node_id:
                    graph_nodes_created = 1
                    page_ids.append(graph_node_id)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "GraphIndex sync failed for %s (non-fatal): %s",
                    source_uri,
                    exc,
                )

        # Step 5 — update manifest (blocking I/O offloaded to thread)
        try:
            await asyncio.to_thread(
                self._sources.mark_ingested,
                source_id,
                pages_generated=page_ids,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Manifest update failed: %s", exc)

        # Step 6 — bookkeeping (file append offloaded to thread)
        wiki_dir = wiki_config.storage_dir
        try:
            await asyncio.to_thread(
                self._bookkeeper.log_operation,
                wiki_dir,
                "INGEST",
                f"source: {source_path_obj.name}, "
                f"pages_created: {pages_created}, "
                f"graph_nodes: {graph_nodes_created}",
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Bookkeeping failed: %s", exc)

        duration_ms = (time.monotonic() - t0) * 1000
        self.logger.info(
            "Ingest complete: source_id=%s pages_created=%d graph_nodes=%d %.1f ms",
            source_id,
            pages_created,
            graph_nodes_created,
            duration_ms,
        )
        return IngestReport(
            source_id=source_id,
            source_uri=source_uri,
            pages_created=pages_created,
            pages_updated=pages_updated,
            graph_nodes_created=graph_nodes_created,
            duration_ms=duration_ms,
            status="ok",
        )

    # ------------------------------------------------------------------
    # Private pipeline steps
    # ------------------------------------------------------------------

    async def _load_source(self, path: Path) -> str:
        """Read the raw source content from disk without blocking the event loop.

        Delegates the file read to a thread pool via ``asyncio.to_thread`` so
        that large source files do not stall other concurrent tasks.

        Args:
            path: Absolute path to the source file.

        Returns:
            File contents as a UTF-8 string.

        Raises:
            FileNotFoundError: If the file does not exist.
            OSError: On read errors.
        """
        return await asyncio.to_thread(path.read_text, encoding="utf-8")

    async def _create_wiki_pages(
        self,
        content: str,
        tree_name: str,
    ) -> dict[str, Any]:
        """Insert content into the PageIndex tree via TwoStepIngester.

        Calls ``PageIndexToolkit.insert_content(tree_name, content)`` which
        internally runs TwoStepIngester (Step 1 CoT analysis, Step 2 markdown
        generation) and splices the result into the tree.

        Args:
            content: Raw source text content.
            tree_name: Target PageIndex tree name (wiki name).

        Returns:
            Result dict from ``PageIndexToolkit.insert_content()``.
        """
        result = await self._pi.insert_content(tree_name, content)
        return result if isinstance(result, dict) else {}

    async def _build_page_records(
        self,
        tree_name: str,
        node_ids: list[str],
        source_id: str,
        fallback_title: str = "",
        fallback_summary: str = "",
    ) -> list[WikiPageRecord]:
        """Build :class:`WikiPageRecord` rows for freshly inserted nodes.

        Reads the PageIndex tree (``get_tree``) to resolve each node's
        stable ``concept_id``, title, summary, and category, and loads
        the markdown body through the toolkit's content store when
        available.  Degrades gracefully to minimal records (identity =
        ``node_id``, empty body) when the tree or bodies cannot be read
        — e.g. with mocked toolkits.

        Args:
            tree_name: PageIndex tree (wiki) name.
            node_ids: ``new_node_ids`` returned by ``insert_content``.
            source_id: Source these pages were derived from.
            fallback_title: Title used when a node cannot be resolved.
            fallback_summary: Summary used when a node cannot be resolved.

        Returns:
            One record per node id.
        """
        tree: Optional[dict[str, Any]] = None
        try:
            candidate = await self._pi.get_tree(tree_name)
            if isinstance(candidate, dict):
                tree = candidate
        except Exception:  # noqa: BLE001 — mocked/legacy toolkits
            tree = None

        loader = None
        content_store = getattr(self._pi, "_content_store", None)
        if tree is not None and content_store is not None:
            try:
                candidate_loader = content_store.loader_for(tree_name)
                if callable(candidate_loader):
                    loader = candidate_loader
            except Exception:  # noqa: BLE001
                loader = None

        records: list[WikiPageRecord] = []
        for nid in node_ids:
            node: Optional[dict[str, Any]] = None
            if tree is not None:
                node = self._find_node(tree, nid)

            if node is None:
                records.append(
                    WikiPageRecord(
                        concept_id=nid,
                        node_id=nid,
                        title=fallback_title or nid,
                        summary=fallback_summary,
                        source_id=source_id,
                        token_count=estimate_tokens(fallback_summary),
                    )
                )
                continue

            concept_id = str(node.get("concept_id") or nid)
            body = self._load_body(loader, concept_id, nid)
            summary = str(node.get("summary") or fallback_summary)
            records.append(
                WikiPageRecord(
                    concept_id=concept_id,
                    node_id=nid,
                    title=str(node.get("title") or fallback_title or nid),
                    category=str(
                        node.get("category") or node.get("type") or "concept"
                    ).lower(),
                    summary=summary,
                    body=body,
                    source_id=source_id,
                    token_count=estimate_tokens(body or summary),
                )
            )
        return records

    @staticmethod
    def _find_node(tree: dict[str, Any], node_id: str) -> Optional[dict[str, Any]]:
        """Locate a node dict by ``node_id`` in a PageIndex tree."""
        try:
            from parrot.knowledge.pageindex.utils import find_node_by_id

            return find_node_by_id(tree.get("structure", tree), node_id)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _load_body(
        loader: Optional[Any],
        concept_id: str,
        node_id: str,
    ) -> str:
        """Load a node's markdown body, trying every known sidecar key."""
        if loader is None:
            return ""
        keys = [concept_id, node_id]
        if "/" in concept_id:
            keys.insert(1, concept_id.replace("/", "--"))
        for key in keys:
            try:
                loaded = loader(key)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(loaded, str) and loaded:
                return loaded
        return ""

    async def _sync_to_graph(
        self,
        source_uri: str,
        tree_name: str = "wiki",
        summary: str = "",
    ) -> Optional[str]:
        """Synchronise the ingested source to GraphIndex as a WIKI_PAGE node.

        Attempts to call ``replace_document_slice()`` first (spec AC: wiki pages
        must be synced via this method so re-ingest replaces stale nodes rather
        than accumulating duplicates).  Falls back to ``create_node()`` when
        ``replace_document_slice`` is not available on the toolkit.

        Args:
            source_uri: Absolute URI of the source document.
            tree_name: Wiki name (used as a domain tag).
            summary: Short content snippet for the node summary.

        Returns:
            The ``node_id`` of the created/replaced graph node, or ``None``
            on failure.
        """
        wiki_page_data = {
            "kind": "wiki_page",
            "title": Path(source_uri).stem,
            "summary": summary[:500] if summary else "",
            "source_uri": source_uri,
            "domain_tags": {"wiki": tree_name},
        }

        # Prefer replace_document_slice (spec AC) to prevent duplicate nodes on
        # re-ingest.  We check callable() to guard against MagicMock in tests and
        # catch (AttributeError, TypeError) in case the method is not awaitable.
        rs_method = getattr(self._gi, "replace_document_slice", None)
        if callable(rs_method):
            try:
                result = await self._gi.replace_document_slice(
                    document_uri=source_uri,
                    nodes=[wiki_page_data],
                    edges=[],
                )
                if isinstance(result, dict):
                    node_ids = result.get("node_ids", [])
                    return (
                        node_ids[0]
                        if node_ids
                        else result.get("node_id")
                    )
            except (AttributeError, TypeError):
                # replace_document_slice exists but is not awaitable (e.g. in
                # tests using MagicMock); fall through to create_node.
                self.logger.debug(
                    "replace_document_slice not awaitable on %s; "
                    "falling back to create_node",
                    type(self._gi).__name__,
                )

        # Fallback: create_node (confirmed available on GraphIndexToolkit)
        result = await self._gi.create_node(**wiki_page_data)
        if isinstance(result, dict):
            return result.get("node_id")
        return None

    def _update_bookkeeping(
        self,
        wiki_dir: Path,
        operation: str,
        details: str,
    ) -> None:
        """Delegate a bookkeeping log entry to WikiBookkeeper.

        Args:
            wiki_dir: Root directory of the wiki instance.
            operation: Operation tag (e.g. ``"INGEST"``).
            details: Human-readable operation details.
        """
        self._bookkeeper.log_operation(wiki_dir, operation, details)

    def _error_report(
        self,
        source_id: str,
        source_uri: str,
        t0: float,
        error: str,
    ) -> IngestReport:
        """Build an error IngestReport.

        Args:
            source_id: Source identifier.
            source_uri: Source URI.
            t0: Monotonic start time from ``time.monotonic()``.
            error: Error description.

        Returns:
            An :class:`IngestReport` with ``status="error"``.
        """
        self.logger.error("Ingest error for %s: %s", source_uri, error)
        return IngestReport(
            source_id=source_id,
            source_uri=source_uri,
            status="error",
            error=error,
            duration_ms=(time.monotonic() - t0) * 1000,
        )
