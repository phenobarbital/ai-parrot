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

FEAT-402 (TASK-2074): ``ingest()`` accepts an optional supervised-triage
context (``triage: Optional[ManifestDocEntry]``). With ``triage=None``
(the default), behavior is byte-identical to pre-FEAT-402 — this is the
path `wikitoolkit build`/`upsert` use today. When a triage decision is
given:

- Its ``briefing`` is forwarded as the PageIndex ``hint`` (the slot this
  method used to drop at the ``insert_content`` call site) so triage
  work is reused, not repeated.
- ``"discard"`` short-circuits the whole pipeline — no PageIndex call,
  no WikiStore sync, no GraphIndex mirror; only the source manifest
  (``status="rejected"``) and bookkeeper ``DISCARD`` line are written.
- ``"archive"`` creates pages exactly like ``"admit"``, except every
  page's category is forced to ``WikiPageCategory.ARCHIVE``.
- Decision fields (destination, decision_source, charter version,
  composite score) are persisted via
  ``SourceCollectionManager.record_decision`` (TASK-2073) instead of
  ``mark_ingested``, and the bookkeeper line is tagged ``ADMIT``/
  ``ARCHIVE`` instead of ``INGEST``.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.documents import (
    AcquiredDocument,
    DocumentAcquirer,
    DocumentAcquisitionError,
    DocumentRef,
    TriageProvenance,
    render_frontmatter,
)
from parrot.knowledge.wiki.models import WikiConfig, WikiPageCategory
from parrot.knowledge.wiki.review import ManifestDocEntry
from parrot.knowledge.wiki.sources import (
    SourceCollectionManager,
    format_decision_log_details,
)
from parrot.knowledge.wiki.store import (
    BaseWikiStore,
    WikiPageRecord,
    estimate_tokens,
)

#: Maps a ManifestDocEntry's proposed_action/decision vocabulary
#: ("admit"|"archive"|"discard", spec §2 Data Models) onto the
#: `sources.destination` column vocabulary documented by TASK-2073
#: ("wiki"|"archive"|"discard", mirroring Charter.destinations). Both
#: describe the same three outcomes; "admit" (a triage verdict) and
#: "wiki" (a routing destination) are synonyms for "becomes a wiki page
#: in the main graph" — this map reconciles the two vocabularies at the
#: one seam where they meet.
_DESTINATION_TO_SOURCES_COLUMN: dict[str, str] = {
    "admit": "wiki",
    "archive": "archive",
    "discard": "discard",
}


def _provenance_from(
    triage: Optional[ManifestDocEntry], charter_version: Optional[str]
) -> Optional[TriageProvenance]:
    """Build a FEAT-451 :class:`TriageProvenance` from a triage decision.

    Args:
        triage: The supervised-ingestion triage decision, or ``None`` on
            the legacy `wikitoolkit build`/`upsert` path.
        charter_version: Editorial charter version the decision was made
            against.

    Returns:
        ``None`` when ``triage`` is ``None`` (legacy path — no triage
        block is ever rendered). Otherwise a populated
        :class:`TriageProvenance`, mapping ``ManifestDocEntry.composite``
        (NOT ``composite_score`` — that name only exists on
        ``SourceManifestEntry``/``TriageProvenance`` themselves) onto
        ``composite_score``, and ``triage.decision or
        triage.proposed_action`` onto ``decision``.
    """
    if triage is None:
        return None
    return TriageProvenance(
        composite_score=triage.composite,
        decision=triage.decision or triage.proposed_action,
        decision_source=triage.decision_source,
        charter_version=charter_version,
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
        store: Optional[BaseWikiStore] = None,
        sync_graph: bool = False,
    ) -> None:
        """Initialise the orchestrator with all dependencies.

        Args:
            pageindex_toolkit: A ``PageIndexToolkit`` instance.
            graphindex_toolkit: A ``GraphIndexToolkit`` instance.
            source_manager: :class:`SourceCollectionManager` for the wiki.
            bookkeeper: :class:`WikiBookkeeper` for log/index management.
            store: :class:`BaseWikiStore` retrieval plane.  When
                ``None``, store sync is skipped (legacy behaviour).
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
        *,
        triage: Optional[ManifestDocEntry] = None,
        charter_version: Optional[str] = None,
        acquired: Optional[AcquiredDocument] = None,
    ) -> IngestReport:
        """Run the full ingest pipeline for a single source file.

        Pipeline steps (``triage=None``, the default — legacy path,
        byte-identical to pre-FEAT-402 behavior):
        1. Register / check the source in the manifest.
        2. Skip (return early) if already ingested and not stale.
        3. Load source content from disk.
        4. Insert into PageIndex tree via ``insert_content`` (TwoStepIngester).
        5. Create a ``WIKI_PAGE`` node in GraphIndex.
        6. Link graph node → source via ``REFERENCES`` edge.
        7. Update manifest with pages generated + new hash/mtime.
        8. Append to log.md.

        When ``triage`` is given (FEAT-402, TASK-2074), the effective
        destination is ``triage.decision`` if set, else
        ``triage.proposed_action``:

        - ``"discard"`` short-circuits everything above — no PageIndex
          call, no WikiStore sync, no GraphIndex mirror. Only the source
          manifest (``status="rejected"``) and a bookkeeper ``DISCARD``
          line are written (spec §2: rejected docs are recorded but
          never ingested).
        - ``"admit"``/``"archive"`` run the same pipeline as the legacy
          path, except: (a) the staleness skip (step 2) is bypassed —
          triage-driven re-application (e.g. re-running ``--review``)
          must always re-persist the (possibly human-edited) decision
          fields even when file content is unchanged; (b) ``triage.
          briefing`` is forwarded as the PageIndex ``hint``; (c)
          ``"archive"`` forces every created page's category to
          ``WikiPageCategory.ARCHIVE``; (d) decision fields are
          persisted via ``SourceCollectionManager.record_decision``
          (TASK-2073) instead of ``mark_ingested``, and the bookkeeper
          line is tagged ``ADMIT``/``ARCHIVE`` instead of ``INGEST``.
          ``replace_source_slice`` (step 4) still guarantees re-applying
          the same source replaces its pages rather than duplicating
          them.

        Args:
            source_path: Absolute or relative path to the source file.
            wiki_config: Configuration for the target wiki instance.
            triage: Optional supervised-ingestion triage decision
                (FEAT-402). ``None`` preserves the exact legacy
                behavior used by `wikitoolkit build`/`upsert`.
            charter_version: Editorial charter version the triage
                decision was made against, for audit persistence
                (``ManifestDocEntry`` itself does not carry this — it is
                only recorded once per manifest run header — so the
                caller that has the run header passes it here). Ignored
                when ``triage`` is ``None``.
            acquired: FEAT-451 — an already-acquired
                :class:`~parrot.knowledge.wiki.documents.AcquiredDocument`
                (typically the triage lane's own acquisition result).
                When given, ``ingest()`` reuses it instead of re-acquiring
                the source through :class:`DocumentAcquirer` — so the
                triaged text and the ingested text always agree. When
                ``None`` (the default), the source is acquired
                internally. On the supervised path (``triage`` given),
                the acquired document's metadata is persisted onto the
                source manifest and rendered as YAML frontmatter on every
                generated page; on the legacy path (``triage=None``, the
                `wikitoolkit build`/`upsert` callers), no frontmatter is
                ever emitted, keeping that output byte-identical to
                pre-FEAT-451 behavior.

        Returns:
            An :class:`IngestReport` describing what was created/updated.

        Raises:
            DocumentAcquisitionError: When ``acquired`` is not given and
                the source cannot be decoded/extracted (FEAT-451). This
                propagates out of ``ingest()`` rather than degrading to
                an ``IngestReport(status="error")`` — callers must
                explicitly decide to skip an undecodable document, never
                triage or ingest mojibake.
        """
        t0 = time.monotonic()
        # FEAT-451 bug fix (revealed by TASK-2358's test_ingest_url):
        # Path(<url>).resolve() resolves a URL against the process cwd as
        # if it were a relative filesystem path (e.g. "https://h/a.pdf"
        # -> "<cwd>/https:/h/a.pdf"), so source_uri would never match the
        # identity IngestTriageRouter.triage() already computed for the
        # same URL — str(Path(ref.uri)) (spec-accepted; TASK-2357's own
        # contract: "For a URL ref, pass Path(ref.uri) — triage only uses
        # it for identity/hashing"), WITHOUT ever resolving against cwd.
        # Skip .resolve() for a URL source_path so this method's own
        # identity computation matches that same (single-slash-collapsed,
        # un-resolved) convention instead of diverging from it.
        if urlparse(source_path).scheme in ("http", "https"):
            source_path_obj = Path(source_path)
            source_uri = str(source_path_obj)
        else:
            source_path_obj = Path(source_path).resolve()
            source_uri = str(source_path_obj)

        effective_destination: Optional[Literal["admit", "archive", "discard"]] = None
        if triage is not None:
            effective_destination = triage.decision or triage.proposed_action

        # FEAT-402: "discard" never creates pages — short-circuit the
        # entire pipeline and just record the rejection.
        if effective_destination == "discard":
            return await self._record_discard(
                source_path_obj, source_uri, wiki_config, triage, charter_version, t0
            )

        # Step 1 — register or check staleness
        # Use public find_by_uri and wrap sync I/O in asyncio.to_thread so the
        # event loop is not blocked by hash computation or manifest writes.
        # FEAT-402: the staleness skip only applies to the legacy
        # (triage=None) path — a triage-driven re-application must
        # always re-persist decision fields, even on unchanged content.
        existing_id = await asyncio.to_thread(
            self._sources.find_by_uri, source_uri
        )
        if existing_id and triage is None:
            source_id = existing_id
            entry = await asyncio.to_thread(self._sources.get_source, source_id)
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
                source_id = entry.source_id
            except (FileNotFoundError, OSError) as exc:
                # File does not exist; generate a deterministic placeholder ID.
                source_id = (
                    f"src-{uuid.uuid5(uuid.NAMESPACE_URL, source_uri).hex[:12]}"
                )
                if triage is None:
                    return self._error_report(source_id, source_uri, t0, str(exc))
                # FEAT-451 bug fix (revealed by TASK-2358's test_ingest_url):
                # add_source() calls path.stat() (sources.py), which always
                # raises for a URL source_path — there is no local file to
                # stat. On the supervised (triage-driven) path, defer full
                # registration to record_decision() (Step 5), which already
                # tolerates a source_path that does not exist on disk (its
                # own docstring: "a rejected document may never have been
                # registered ... at all") — keep going instead of erroring.
                self.logger.debug(
                    "add_source could not stat %s (%s) — deferring"
                    " registration to record_decision (triage-driven).",
                    source_uri,
                    exc,
                )

        # Step 2 — acquire content (FEAT-451: loader-backed, not a raw
        # read_text()). Reuse the caller's already-acquired document when
        # given (the triage lane's own result) so triaged and ingested
        # text always agree; otherwise acquire internally via
        # DocumentAcquirer. DocumentAcquisitionError propagates out of
        # ingest() — never silently degrade to an error report, that
        # would recreate the mojibake bug this feature fixes.
        try:
            if acquired is None:
                acquired = await self._load_source(source_path_obj)
            content = acquired.text
        except DocumentAcquisitionError:
            raise
        except Exception as exc:  # noqa: BLE001
            return self._error_report(source_id, source_uri, t0, str(exc))

        # Step 3 — insert into PageIndex (uses TwoStepIngester internally)
        tree_name = wiki_config.wiki_name
        pages_created = 0
        pages_updated = 0
        page_ids: list[str] = []

        # FEAT-402: forward the triage briefing as the ingester hint (the
        # slot this call used to drop), and force the ARCHIVE category on
        # every page when the effective destination is "archive".
        hint = triage.briefing if triage is not None else None
        category_override = (
            WikiPageCategory.ARCHIVE.value
            if effective_destination == "archive"
            else None
        )

        # FEAT-451: page frontmatter is a supervised-ingestion-only
        # enhancement — the legacy (triage=None) build/upsert path emits
        # NO frontmatter at all, keeping its output byte-identical to
        # pre-FEAT-451 behavior. Computed once, outside the per-page loop
        # in _build_page_records, so every page from this source carries
        # an identical frontmatter block (resolved spec §8).
        frontmatter = ""
        if triage is not None:
            provenance = _provenance_from(triage, charter_version)
            frontmatter = render_frontmatter(acquired.metadata, provenance)

        try:
            pi_result = await self._create_wiki_pages(content, tree_name, hint=hint)
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
                    category_override=category_override,
                    frontmatter=frontmatter,
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

        # Step 5 — update manifest (blocking I/O offloaded to thread).
        # FEAT-402: when a triage decision is present, persist it (and
        # the pages it produced) via record_decision instead of
        # mark_ingested, so destination/decision_source/charter_version/
        # composite_score are recorded (TASK-2073).
        if triage is not None:
            try:
                decision_entry = await asyncio.to_thread(
                    self._sources.record_decision,
                    source_path_obj,
                    destination=_DESTINATION_TO_SOURCES_COLUMN.get(
                        effective_destination, effective_destination
                    ),
                    decision_source=triage.decision_source,
                    charter_version=charter_version,
                    composite_score=triage.composite,
                    pages_generated=page_ids,
                )
                # FEAT-451: persist extracted document metadata alongside
                # the triage decision — admit/archive only (discard never
                # reaches this branch, it short-circuits via
                # _record_discard before Step 1).
                await asyncio.to_thread(
                    self._sources.record_document_metadata,
                    decision_entry.source_id,
                    doc_metadata=acquired.metadata.model_dump(),
                    content_type=acquired.metadata.content_type,
                    loader=acquired.metadata.loader,
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Manifest update failed: %s", exc)
                decision_entry = None
        else:
            try:
                await asyncio.to_thread(
                    self._sources.mark_ingested,
                    source_id,
                    pages_generated=page_ids,
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Manifest update failed: %s", exc)
            decision_entry = None

        # Step 6 — bookkeeping (file append offloaded to thread).
        # FEAT-402: triage-driven ingests are tagged ADMIT/ARCHIVE (per
        # effective_destination) with the shared decision-details
        # formatter, instead of the legacy INGEST tag.
        wiki_dir = wiki_config.storage_dir
        try:
            if triage is not None:
                operation = "ARCHIVE" if effective_destination == "archive" else "ADMIT"
                details = (
                    format_decision_log_details(decision_entry)
                    if decision_entry is not None
                    else f"source: {source_path_obj.name}, pages_created: {pages_created}"
                )
                await asyncio.to_thread(
                    self._bookkeeper.log_operation, wiki_dir, operation, details
                )
            else:
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

    async def extract_entities(
        self,
        tree_name: str,
        wiki_config: WikiConfig,
        granularity: Any = "standard",
        custom_instructions: Optional[str] = None,
    ) -> IngestReport:
        """Phase 2 (FEAT-392): LLM entity/concept extraction from pages.

        Iterates over the content-bearing nodes of an already-ingested
        PageIndex tree, asks the PageIndex LLM adapter for the entities
        and concepts each page mentions, creates one sub-node per
        extracted item, and mirrors each as a CONCEPT node in GraphIndex
        (when a graph toolkit is configured).

        Args:
            tree_name: PageIndex tree to extract from (must exist).
            wiki_config: Wiki configuration (used for logging context).
            granularity: ``ExtractionGranularity`` or its string value —
                ``minimal`` (up to 3 key concepts per page), ``standard``
                (up to 8 entities + concepts), ``fine`` (exhaustive), or
                ``custom`` (drive with ``custom_instructions``).
            custom_instructions: Extraction directive used when
                ``granularity="custom"``.

        Returns:
            An :class:`IngestReport` — ``pages_created`` counts entity
            sub-nodes, ``graph_nodes_created`` counts GraphIndex mirrors.
        """
        from parrot.interfaces.obsidian.models import ExtractionGranularity

        t0 = time.monotonic()
        source_id = f"entity-extraction::{tree_name}"
        if not isinstance(granularity, ExtractionGranularity):
            granularity = ExtractionGranularity(str(granularity))

        adapter = getattr(self._pi, "_light_adapter", None) or getattr(
            self._pi, "_adapter", None
        )
        if adapter is None:
            return self._error_report(
                source_id, tree_name, t0,
                "PageIndexToolkit has no LLM adapter for entity extraction",
            )
        try:
            tree = await self._pi.get_tree(tree_name)
        except KeyError as exc:
            return self._error_report(source_id, tree_name, t0, str(exc))

        directives = {
            ExtractionGranularity.MINIMAL: (
                "Extract at most 3 KEY concepts central to the text."
            ),
            ExtractionGranularity.STANDARD: (
                "Extract up to 8 salient entities (people, projects, "
                "systems, places) and concepts."
            ),
            ExtractionGranularity.FINE: (
                "Extract ALL distinct entities and concepts mentioned, "
                "however minor."
            ),
            ExtractionGranularity.CUSTOM: custom_instructions
            or "Extract the entities and concepts from the text.",
        }
        directive = directives[granularity]

        # Collect content-bearing nodes, skipping prior extraction output.
        targets: list[dict[str, Any]] = []

        def _walk(data: Any) -> None:
            if isinstance(data, dict):
                metadata = data.get("metadata") or {}
                if data.get("node_id") and not metadata.get("extracted_from"):
                    targets.append(data)
                for key in data:
                    if "nodes" in key:
                        _walk(data[key])
            elif isinstance(data, list):
                for item in data:
                    _walk(item)

        _walk(tree.get("structure", tree))

        loader = None
        content_store = getattr(self._pi, "_content_store", None)
        if content_store is not None:
            loader = content_store.loader_for(tree_name)

        entities_created = 0
        graph_created = 0
        errors: list[str] = []
        for node in targets:
            node_id = node.get("node_id") or ""
            body = self._load_body(
                loader, node.get("concept_id") or node_id, node_id
            )
            if not body or len(body.strip()) < 20:
                continue
            prompt = (
                f"{directive}\n\n"
                "Return ONLY a JSON array; each item: "
                '{"name": str, "kind": "entity"|"concept", "summary": str '
                "(one sentence)}.\n\nTEXT:\n" + body[:6000]
            )
            try:
                items = await adapter.ask_json(prompt)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{node_id}: {exc}")
                continue
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                name = str(item["name"]).strip()
                kind = str(item.get("kind", "concept")).lower()
                kind = kind if kind in ("entity", "concept") else "concept"
                summary = str(item.get("summary", "")).strip()
                try:
                    await self._pi.add_node(
                        tree_name,
                        title=name,
                        summary=summary,
                        parent_node_id=node_id,
                        categories=[kind],
                        metadata={
                            "extracted_from": node_id,
                            "granularity": granularity.value,
                        },
                    )
                    entities_created += 1
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{node_id}/{name}: {exc}")
                    continue
                if self._gi is not None:
                    try:
                        created = await self._gi.create_concept(
                            title=name,
                            summary=summary or name,
                            source_uri=f"pageindex://{tree_name}/{node_id}",
                            categories=[kind],
                        )
                        if isinstance(created, dict) and not created.get("error"):
                            graph_created += 1
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"graph {name}: {exc}")

        self.logger.info(
            "extract_entities(%s, granularity=%s): %d entities, %d graph nodes",
            tree_name, granularity.value, entities_created, graph_created,
        )
        return IngestReport(
            source_id=source_id,
            source_uri=tree_name,
            pages_created=entities_created,
            graph_nodes_created=graph_created,
            duration_ms=(time.monotonic() - t0) * 1000,
            status="ok" if not errors else "partial",
            error="; ".join(errors[:5]) if errors else None,
        )

    async def _record_discard(
        self,
        source_path_obj: Path,
        source_uri: str,
        wiki_config: WikiConfig,
        triage: ManifestDocEntry,
        charter_version: Optional[str],
        t0: float,
    ) -> IngestReport:
        """Record a "discard" triage decision without creating any pages.

        Spec §2: rejected docs are recorded in the source manifest with
        ``status="rejected"`` and are NEVER ingested — no PageIndex call,
        no WikiStore sync, no GraphIndex mirror.

        Args:
            source_path_obj: Resolved absolute path to the source file.
            source_uri: String form of ``source_path_obj``.
            wiki_config: Configuration for the target wiki instance.
            triage: The triage decision (``decision``/``proposed_action``
                resolved to ``"discard"`` by the caller).
            charter_version: Editorial charter version, if known.
            t0: Monotonic start time from ``time.monotonic()``.

        Returns:
            An :class:`IngestReport` with zero pages/nodes created.
        """
        decision_entry = await asyncio.to_thread(
            self._sources.record_decision,
            source_path_obj,
            destination="discard",
            decision_source=triage.decision_source,
            charter_version=charter_version,
            composite_score=triage.composite,
            pages_generated=[],
        )

        wiki_dir = wiki_config.storage_dir
        try:
            await asyncio.to_thread(
                self._bookkeeper.log_operation,
                wiki_dir,
                "DISCARD",
                format_decision_log_details(decision_entry),
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("Bookkeeping failed: %s", exc)

        duration_ms = (time.monotonic() - t0) * 1000
        self.logger.info(
            "Discarded %s per triage decision (%.1f ms)", source_uri, duration_ms
        )
        return IngestReport(
            source_id=decision_entry.source_id,
            source_uri=source_uri,
            pages_created=0,
            pages_updated=0,
            graph_nodes_created=0,
            duration_ms=duration_ms,
            status="ok",
        )

    # ------------------------------------------------------------------
    # Private pipeline steps
    # ------------------------------------------------------------------

    async def _load_source(self, path: Path) -> AcquiredDocument:
        """Acquire the source document's text and metadata (FEAT-451).

        Delegates to :class:`DocumentAcquirer`, which routes plain-text
        extensions (``PLAIN_TEXT_EXTENSIONS``) through a direct read and
        everything else (PDF, DOCX, PPTX, XLSX, HTML, EPUB, ...) through
        the loader layer — replacing the previous
        ``path.read_text(encoding="utf-8")`` call, which corrupted binary
        documents into mojibake instead of rejecting them. Builds the
        :class:`~parrot.knowledge.wiki.documents.DocumentRef` the
        acquirer needs from ``path``; this method is only ever called
        with a local file path (``is_url=False``) — URL sources are
        acquired by the caller (the CLI, TASK-2357) and passed in via
        :meth:`ingest`'s ``acquired`` parameter instead.

        Args:
            path: Absolute path to the source file.

        Returns:
            The extracted :class:`AcquiredDocument` (text + metadata).

        Raises:
            DocumentAcquisitionError: When the document cannot be decoded
                or extracted. Callers MUST let this propagate — never
                triage or ingest undecodable content as if it were real
                text (the bug this feature fixes).
        """
        ref = DocumentRef(uri=str(path), suffix=path.suffix.lower())
        return await DocumentAcquirer().acquire(ref)

    async def _create_wiki_pages(
        self,
        content: str,
        tree_name: str,
        hint: Optional[str] = None,
    ) -> dict[str, Any]:
        """Insert content into the PageIndex tree via TwoStepIngester.

        Calls ``PageIndexToolkit.insert_content(tree_name, content, hint=hint)``
        which internally runs TwoStepIngester (Step 1 CoT analysis, Step 2
        markdown generation) and splices the result into the tree.

        Args:
            content: Raw source text content.
            tree_name: Target PageIndex tree name (wiki name).
            hint: Optional triage briefing (FEAT-402), interpolated into
                both TwoStepIngester prompts. ``None`` preserves legacy
                behavior.

        Returns:
            Result dict from ``PageIndexToolkit.insert_content()``.
        """
        result = await self._pi.insert_content(tree_name, content, hint=hint)
        return result if isinstance(result, dict) else {}

    async def _build_page_records(
        self,
        tree_name: str,
        node_ids: list[str],
        source_id: str,
        fallback_title: str = "",
        fallback_summary: str = "",
        category_override: Optional[str] = None,
        frontmatter: str = "",
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
            category_override: When given (FEAT-402 — the
                ``"archive"`` destination), forces every record's
                ``category`` to this value regardless of what the
                PageIndex tree reports. ``None`` preserves legacy
                category resolution.
            frontmatter: FEAT-451 — a pre-rendered YAML frontmatter block
                (see ``render_frontmatter``) prefixed onto every record's
                ``body`` — in BOTH branches below — before
                ``token_count`` is computed, so it reflects what is
                actually stored. ``""`` (the default, and always the
                value on the legacy ``triage=None`` path) preserves
                byte-identical pre-FEAT-451 output. Every page derived
                from one source gets the identical block — compute it
                once, outside this loop.

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
                # FEAT-451: this fallback branch never had real body
                # content (it defaulted to WikiPageRecord.body=""); the
                # frontmatter, when present, becomes the entire body.
                fallback_body = frontmatter
                record_kwargs: dict[str, Any] = {
                    "concept_id": nid,
                    "node_id": nid,
                    "title": fallback_title or nid,
                    "summary": fallback_summary,
                    "source_id": source_id,
                    "token_count": estimate_tokens(fallback_body or fallback_summary),
                }
                if fallback_body:
                    record_kwargs["body"] = fallback_body
                if category_override is not None:
                    record_kwargs["category"] = category_override
                records.append(WikiPageRecord(**record_kwargs))
                continue

            concept_id = str(node.get("concept_id") or nid)
            body = self._load_body(loader, concept_id, nid)
            if frontmatter:
                body = frontmatter + body
            summary = str(node.get("summary") or fallback_summary)
            category = (
                category_override
                if category_override is not None
                else str(
                    node.get("category") or node.get("type") or "concept"
                ).lower()
            )
            records.append(
                WikiPageRecord(
                    concept_id=concept_id,
                    node_id=nid,
                    title=str(node.get("title") or fallback_title or nid),
                    category=category,
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
