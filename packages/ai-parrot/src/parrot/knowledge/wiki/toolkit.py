"""LLMWikiToolkit — agent-facing orchestrator for the LLM Wiki (FEAT-260).

Composes :class:`PageIndexToolkit`, :class:`GraphIndexToolkit`, and
:class:`OKFToolkit` into Karpathy's 3-layer wiki architecture.  Every
public async method becomes an LLM-callable tool namespaced under the
``"wiki"`` prefix (e.g. ``wiki_ingest_source``, ``wiki_query``, etc.).

Layer mapping:
- **Raw Sources** — managed by :class:`SourceCollectionManager`
- **Wiki Pages** — stored in PageIndex trees; synced to GraphIndex nodes
- **Schema** — OKF ConceptType / RelationType extensions (FEAT-260)

All async methods accept JSON-serialisable arguments and return plain
dicts so that tool responses are directly usable as LLM context.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.context import (
    DEFAULT_BUDGET_TOKENS,
    pack_results,
    truncate_to_tokens,
)
from parrot.knowledge.wiki.ingest import IngestReport, WikiIngestOrchestrator
from parrot.knowledge.wiki.models import (
    WikiConfig,
    WikiLintReport,
    WikiPageCategory,
)
from parrot.knowledge.wiki.search import WikiCombinedSearch
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import (
    BaseWikiStore,
    WikiPageRecord,
    create_wiki_store,
    estimate_tokens,
)
from parrot.tools.toolkit import AbstractToolkit


def _is_federated(store: Any) -> bool:
    """Whether ``store`` is a :class:`FederatedWikiStore` (lazy import)."""
    from parrot.knowledge.wiki.federation import FederatedWikiStore

    return isinstance(store, FederatedWikiStore)


class LLMWikiToolkit(AbstractToolkit):
    """Orchestrates PageIndex + GraphIndex + OKF into a persistent LLM wiki.

    This is the agent-facing surface of FEAT-260.  Construct with three
    toolkit dependencies and a :class:`WikiConfig`, then call
    ``get_tools()`` to obtain the list of LLM-callable tools.

    Tool prefix: ``"wiki"`` — all tools are namespaced as
    ``wiki_<method_name>`` (e.g. ``wiki_ingest_source``, ``wiki_query``).

    Attributes:
        tool_prefix: Set to ``"wiki"`` to namespace all tools.
        _pi: Composed ``PageIndexToolkit`` instance.
        _gi: Composed ``GraphIndexToolkit`` instance.
        _okf: Composed ``OKFToolkit`` instance.
        _config: Per-wiki-instance configuration.
        _sources: :class:`SourceCollectionManager` for source tracking.
        _bookkeeper: :class:`WikiBookkeeper` for index/log management.
        _search: :class:`WikiCombinedSearch` for unified retrieval.
        _ingest: :class:`WikiIngestOrchestrator` for ingest pipeline.

    Example::

        toolkit = LLMWikiToolkit(pi_toolkit, gi_toolkit, okf_toolkit, config)
        tools = toolkit.get_tools()  # registers 18+ tools with the LLM
    """

    tool_prefix: str = "wiki"

    def __init__(
        self,
        pageindex_toolkit: Any,
        graphindex_toolkit: Any,
        okf_toolkit: Any,
        config: WikiConfig,
        agent_id: str = "agent",
        store: Optional[BaseWikiStore] = None,
        **kwargs: Any,
    ) -> None:
        """Initialise the LLMWikiToolkit with composed dependencies.

        Args:
            pageindex_toolkit: A ``PageIndexToolkit`` instance for tree ops.
            graphindex_toolkit: A ``GraphIndexToolkit`` instance for graph ops.
            okf_toolkit: An ``OKFToolkit`` instance for schema/lint ops.
            config: :class:`WikiConfig` for this wiki instance.
            agent_id: Identity stamped (as ``agent:<id>``) onto pages the
                agent authors via ``create_page`` / ``remember``.
            store: Pre-built retrieval plane to use instead of building
                one from ``config``. Pass a
                :class:`~parrot.knowledge.wiki.federation.FederatedWikiStore`
                to give the toolkit access to federated namespaces
                (FEAT-450): ``list_wikis`` then enumerates them and the
                read methods dispatch on ``wiki_name``. Source tracking
                and every write stay on the local plane.
            **kwargs: Forwarded to :class:`AbstractToolkit`.
        """
        super().__init__(**kwargs)
        self._pi = pageindex_toolkit
        self._gi = graphindex_toolkit
        self._okf = okf_toolkit
        self._config = config
        self.agent_id = agent_id

        # Initialise helper components.  The WikiStore plane is the
        # retrieval backend — SQLite (storage_dir/wiki.db), the
        # in-memory + OKF-bundle-directory backend, or a server-hosted
        # ArangoDB backend, per config.
        if store is not None:
            # An injected plane (typically federated) replaces the
            # config-driven construction entirely.
            self._store = store
        elif config.storage_backend == "arangodb":
            # Bypass the factory: ArangoDB connection params come from
            # ARANGODB_* env vars (never from WikiConfig, which carries
            # no arango-specific fields), resolved the same way
            # WikiProjectConfig-driven callers do.
            from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore
            from parrot.knowledge.wiki.project import (
                WikiProjectConfig,
                resolve_arango_params,
            )

            arango_params = resolve_arango_params(
                WikiProjectConfig(wiki_name=config.wiki_name)
            )
            self._store = ArangoDBWikiStore(
                arango_params, wiki_name=config.wiki_name
            )
        else:
            self._store = create_wiki_store(
                config.storage_dir,
                wiki_name=config.wiki_name,
                backend=config.storage_backend,
            )
        # Source tracking is a LOCAL concern — a federated store's
        # namespaces bring their own manifests, which this toolkit never
        # writes. Keep keying it on the config, as before.
        sources_dir = config.storage_dir / "sources"
        if config.storage_backend == "sqlite":
            self._sources = SourceCollectionManager(
                sources_dir, db_path=config.storage_dir / "wiki.db"
            )
        elif config.storage_backend == "arangodb":
            # arango_store (not arango_db): __init__ is synchronous and
            # cannot await self._store.initialize() itself — the manager
            # lazily initializes it (idempotent) on first actual use.
            # With an injected federated store, the manifest still lives
            # in the LOCAL plane's SOURCES collection — reach through to
            # it rather than silently degrading to a JSON manifest that
            # would report every source as missing.
            arango_local = self._local_arango_store()
            if arango_local is None:
                self._sources = SourceCollectionManager(
                    sources_dir, backend="json"
                )
            else:
                self._sources = SourceCollectionManager(
                    sources_dir, backend="arangodb", arango_store=arango_local
                )
        else:
            self._sources = SourceCollectionManager(
                sources_dir, backend="json"
            )
        self._bookkeeper = WikiBookkeeper()
        self._search = WikiCombinedSearch(
            pageindex_toolkit,
            graphindex_toolkit,
            config.search_weights,
            store=self._store,
            # A federated store ranks and weights across namespaces
            # itself; re-normalising here would erase those weights.
            normalize_store_rows=not _is_federated(self._store),
        )
        self._ingest_orch = WikiIngestOrchestrator(
            pageindex_toolkit,
            graphindex_toolkit,
            self._sources,
            self._bookkeeper,
            store=self._store,
            sync_graph=config.sync_graph,
        )
        #: Per-namespace search facades, built lazily by :meth:`_search_for`.
        self._ns_search: dict[str, WikiCombinedSearch] = {}
        self.logger: logging.Logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Namespace dispatch (FEAT-450)
    # ------------------------------------------------------------------

    def _local_arango_store(self) -> Any:
        """The ArangoDB store backing the LOCAL plane, if there is one.

        Unwraps a federated store to its local plane so source tracking
        keeps using the real ``SOURCES`` collection.

        Returns:
            The :class:`ArangoDBWikiStore`, or ``None``.
        """
        from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore

        candidate = getattr(self._store, "local", self._store)
        return candidate if isinstance(candidate, ArangoDBWikiStore) else None

    @property
    def _federated(self) -> Any:
        """The injected store when it is federated, else ``None``."""
        return self._store if _is_federated(self._store) else None

    def _is_namespace(self, wiki_name: str) -> bool:
        """Whether ``wiki_name`` addresses a federated namespace."""
        federated = self._federated
        if federated is None:
            return False
        return wiki_name in federated.namespaces or wiki_name in ("all", "local")

    def _store_for(self, wiki_name: str) -> BaseWikiStore:
        """Return the store serving ``wiki_name``.

        Args:
            wiki_name: The toolkit's own wiki, or a federated namespace
                name / ``"all"`` / ``"local"``.

        Returns:
            The local (or scoped federated) store.
        """
        federated = self._federated
        if federated is None or not self._is_namespace(wiki_name):
            return self._store
        return federated.scoped(wiki_name)

    def _search_for(self, wiki_name: str) -> WikiCombinedSearch:
        """Return the search facade for ``wiki_name`` (cached per namespace)."""
        if not self._is_namespace(wiki_name):
            return self._search
        cached = self._ns_search.get(wiki_name)
        if cached is None:
            cached = WikiCombinedSearch(
                self._pi,
                self._gi,
                self._config.search_weights,
                store=self._store_for(wiki_name),
                normalize_store_rows=False,
            )
            self._ns_search[wiki_name] = cached
        return cached

    # ------------------------------------------------------------------
    # Core Operations (Karpathy's 3)
    # ------------------------------------------------------------------

    async def ingest_source(
        self,
        wiki_name: str,
        source_path: str,
        source_type: Optional[str] = None,
    ) -> dict[str, Any]:
        """Ingest a raw source document into the wiki.

        Processes the source via TwoStepIngester, creates wiki pages in
        PageIndex, syncs them to GraphIndex as WIKI_PAGE nodes, and
        updates the source manifest, index.md, and log.md.

        Args:
            wiki_name: Name of the target wiki.
            source_path: Absolute path to the source file.
            source_type: Optional hint for the ingester (e.g. ``"markdown"``).

        Returns:
            Dict with keys: source_id, pages_created, graph_nodes_created,
            duration_ms, status.
        """
        self.logger.info(
            "Ingesting source into wiki '%s': %s", wiki_name, source_path
        )
        effective_config = self._local_config_for(wiki_name)
        report: IngestReport = await self._ingest_orch.ingest(
            source_path, effective_config
        )
        return report.model_dump()

    async def ingest_obsidian_vault(
        self,
        wiki_name: str,
        vault_path: str,
        incremental: bool = False,
        extract_entities: bool = False,
        granularity: str = "standard",
        extra_skip_patterns: list[str] | None = None,
    ) -> dict[str, Any]:
        """Ingest an Obsidian vault into the wiki (FEAT-392).

        Phase 1 stores one PageIndex node per note (no LLM), Phase 1b
        imports the vault's ``[[wikilink]]`` graph into GraphIndex as
        pre-curated edges, and Phase 2 (opt-in) runs LLM entity/concept
        extraction over the ingested pages.

        Args:
            wiki_name: Name of the target wiki (tree name = wiki name).
            vault_path: Absolute path of the Obsidian vault directory.
            incremental: Only re-ingest added/changed files and prune
                deleted ones (uses the source manifest for staleness).
            extract_entities: Also run Phase-2 LLM entity extraction.
            granularity: Entity extraction granularity — ``minimal``,
                ``standard``, ``fine`` or ``custom``.
            extra_skip_patterns: Additional directory names to exclude
                from vault traversal, on top of the loader's own
                ``.obsidian``/``.trash``/``.git`` defaults — e.g. a
                caller-enforced ``Private/`` boundary that must never be
                read, indexed, or surfaced by any derived plane. ``None``
                preserves the loader's exact prior default behavior.

        Returns:
            Dict with the phase reports: ``raw_ingest``, ``graph_bridge``
            (nodes/edges imported) and optionally ``entity_extraction``.
        """
        from parrot.loaders.obsidian import (
            ObsidianGraphBridge,
            ObsidianVaultLoader,
        )

        self.logger.info(
            "Ingesting Obsidian vault into wiki '%s': %s", wiki_name, vault_path
        )
        effective_config = self._local_config_for(wiki_name)
        loader = ObsidianVaultLoader(vault_path)
        if extra_skip_patterns:
            loader.vault.skip_patterns = loader.vault.skip_patterns | frozenset(extra_skip_patterns)
        if incremental:
            raw_report = await loader.incremental_update(
                self._pi, wiki_name, self._sources
            )
        else:
            raw_report = await loader.ingest(self._pi, wiki_name, self._sources)

        # Phase 1b — wikilink graph import (best-effort, no LLM).
        graph_summary: dict[str, Any] = {
            "nodes_imported": 0, "edges_imported": 0, "errors": []
        }
        if self._gi is not None:
            notes, canvases = await loader.discover()
            bridge = ObsidianGraphBridge(
                notes,
                canvases,
                await loader.vault.build_index(),
                vault_name=loader.vault.vault_name,
            )
            nodes, edges = bridge.build_graph()
            id_map: dict[str, str] = {}
            for node in nodes:
                try:
                    created = await self._gi.create_node(
                        kind=node.kind.value,
                        title=node.title,
                        summary=node.summary,
                        source_uri=node.source_uri,
                        domain_tags=node.domain_tags or None,
                    )
                except Exception as exc:  # noqa: BLE001
                    graph_summary["errors"].append(f"{node.node_id}: {exc}")
                    continue
                if isinstance(created, dict) and created.get("node_id"):
                    id_map[node.node_id] = created["node_id"]
                    graph_summary["nodes_imported"] += 1
                else:
                    graph_summary["errors"].append(
                        f"{node.node_id}: {created!r}"
                    )
            for edge in edges:
                source_id = id_map.get(edge.source_id)
                target_id = id_map.get(edge.target_id)
                if not source_id or not target_id:
                    continue
                try:
                    linked = await self._gi.link_nodes(
                        source_id, target_id, edge.kind.value
                    )
                    if isinstance(linked, dict) and not linked.get("error"):
                        graph_summary["edges_imported"] += 1
                except Exception as exc:  # noqa: BLE001
                    graph_summary["errors"].append(
                        f"{edge.source_id}->{edge.target_id}: {exc}"
                    )
            graph_summary["errors"] = graph_summary["errors"][:10]

        result: dict[str, Any] = {
            "raw_ingest": raw_report.model_dump(),
            "graph_bridge": graph_summary,
        }

        # Phase 2 — opt-in LLM entity extraction.
        if extract_entities:
            entity_report = await self._ingest_orch.extract_entities(
                wiki_name, effective_config, granularity=granularity
            )
            result["entity_extraction"] = entity_report.model_dump()
        return result

    async def query(
        self,
        wiki_name: str,
        question: str,
        file_answer: bool = False,
        mode: str = "combined",
    ) -> dict[str, Any]:
        """Query the wiki and optionally file the answer as a new page.

        Performs combined search across PageIndex and GraphIndex, collects
        top results as context, synthesises an answer (by concatenating
        snippets for now; LLM synthesis can be added when a client is
        available), and optionally creates a new ANSWER page.

        Args:
            wiki_name: Name of the wiki to query.
            question: Natural-language question.
            file_answer: When ``True``, save the synthesised answer as a new
                wiki page with category ANSWER.
            mode: Search mode — ``"combined"``, ``"pageindex"``, or
                ``"graphindex"``.

        Returns:
            Dict with keys: question, answer, sources, filed_page_id.
        """
        results = await self._search.search(
            question, mode=mode, top_k=10, tree_name=wiki_name
        )
        packed = pack_results(results, budget_tokens=DEFAULT_BUDGET_TOKENS)
        answer = self._synthesise_answer(question, packed.text)

        filed_page_id: Optional[str] = None
        if file_answer:
            filed = await self.create_page(
                wiki_name=wiki_name,
                title=f"Answer: {question[:80]}",
                content=f"# {question}\n\n{answer}",
                category=WikiPageCategory.ANSWER.value,
            )
            filed_page_id = filed.get("page_id")

        await asyncio.to_thread(
            self._bookkeeper.log_operation,
            self._config_for(wiki_name).storage_dir,
            "QUERY",
            f"question: {question[:100]!r}, mode: {mode}, filed: {file_answer}",
        )

        return {
            "question": question,
            "answer": answer,
            "sources": [r.model_dump() for r in results],
            "filed_page_id": filed_page_id,
        }

    async def lint(
        self,
        wiki_name: str,
        fix: bool = False,
    ) -> dict[str, Any]:
        """Run OKF lint and wiki-specific checks on the wiki.

        Extends OKF's ``lint_knowledge_base()`` with:
        - Orphan sources (manifest entry with no pages generated)
        - Stale sources (file changed since last ingest)
        - Uncovered sources (known files not yet ingested)

        Args:
            wiki_name: Name of the wiki to lint.
            fix: When ``True``, attempt to fix auto-correctable issues
                (currently no-op — reserved for future implementation).

        Returns:
            A :class:`WikiLintReport` serialised to dict.
        """
        # OKF lint — delegate if OKF toolkit is available
        okf_result: dict[str, Any] = {}
        try:
            okf_result = await self._okf.lint_knowledge_base()
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("OKF lint failed: %s", exc)

        # Wiki-specific checks — answered from the SQLite plane.
        # Orphans: sources with zero derived pages (SQL join); falls back
        # to the registry's pages_generated when the pages table is empty
        # for that source but ids were recorded (e.g. store sync skipped).
        all_sources = await asyncio.to_thread(self._sources.list_sources)
        recorded = {
            s.source_id for s in all_sources if s.pages_generated
        }
        orphan_sources = [
            sid
            for sid in await self._store.orphan_sources()
            if sid not in recorded
        ]
        # is_stale does file I/O (stat + optional hash) — offload to thread pool
        stale_sources: list[str] = []
        for s in all_sources:
            if await asyncio.to_thread(self._sources.is_stale, s.source_id):
                stale_sources.append(s.source_id)

        # Uncovered: files present in source_dir but never registered.
        uncovered_sources: list[str] = []
        source_dir = self._config.source_dir
        if source_dir and Path(source_dir).is_dir():
            tracked_uris = {s.source_uri for s in all_sources}
            for candidate in sorted(Path(source_dir).rglob("*")):
                if candidate.is_file() and str(candidate.resolve()) not in tracked_uris:
                    uncovered_sources.append(str(candidate))

        # Cross-reference issues: broken edges + pages without bodies.
        cross_ref_issues: list[dict[str, Any]] = [
            {"kind": "broken_edge", **edge}
            for edge in await self._store.broken_edges()
        ]
        cross_ref_issues.extend(
            {"kind": "missing_body", "concept_id": cid}
            for cid in await self._store.missing_bodies()
        )

        report = WikiLintReport(
            okf_report=okf_result,
            orphan_sources=orphan_sources,
            stale_sources=stale_sources,
            uncovered_sources=uncovered_sources,
            cross_ref_issues=cross_ref_issues,
        )

        await asyncio.to_thread(
            self._bookkeeper.log_operation,
            self._config_for(wiki_name).storage_dir,
            "LINT",
            f"issues: {report.total_issues}, orphans: {len(orphan_sources)}, "
            f"stale: {len(stale_sources)}",
        )
        return report.model_dump()

    # ------------------------------------------------------------------
    # Wiki Management
    # ------------------------------------------------------------------

    async def create_wiki(
        self,
        wiki_name: str,
        description: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new wiki with its directory structure.

        Creates the following layout under ``config.storage_dir``::

            {storage_dir}/
            ├── sources/         # raw source documents
            ├── wiki.db          # SQLite retrieval plane (pages/edges/FTS)
            ├── index.md         # auto-generated content catalog
            └── log.md           # append-only operation log

        Page content lives in ``wiki.db`` (machine plane), not in
        per-category markdown directories.

        Args:
            wiki_name: Human-readable wiki name.
            description: Optional description written to index.md header.

        Returns:
            Dict with keys: status, wiki_name, storage_dir, directories_created.
        """
        storage_dir = self._config.storage_dir
        directories = [
            storage_dir / "sources",
        ]
        created: list[str] = []
        for d in directories:
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                created.append(str(d))

        # Initialise empty index.md and log.md (file writes offloaded to thread)
        await asyncio.to_thread(
            self._bookkeeper.write_index, storage_dir, tree_name=wiki_name
        )
        await asyncio.to_thread(
            self._bookkeeper.log_operation,
            storage_dir,
            "CREATE",
            f"wiki_name: {wiki_name!r}, description: {description!r}",
        )

        self.logger.info("Created wiki '%s' at %s", wiki_name, storage_dir)
        return {
            "status": "created",
            "wiki_name": wiki_name,
            "storage_dir": str(storage_dir),
            "directories_created": created,
        }

    async def list_wikis(self) -> list[dict[str, Any]]:
        """List every wiki this toolkit can read.

        Always the local wiki; when a federated store was injected
        (FEAT-450), one entry per resolved namespace follows, plus one
        per namespace that could not be opened (``status`` says why).

        Returns:
            List of wiki info dicts. The local entry carries
            ``wiki_name``, ``storage_dir`` and ``source_count``;
            namespace entries add ``kind``, ``origin``, ``read_only``
            and ``status``.
        """
        sources = await asyncio.to_thread(self._sources.list_sources)
        wikis: list[dict[str, Any]] = [
            {
                "wiki_name": self._config.wiki_name,
                "storage_dir": str(self._config.storage_dir),
                "source_count": len(sources),
                "origin": "local",
                "read_only": False,
                "status": "ok",
            }
        ]
        federated = self._federated
        if federated is None:
            return wikis
        for name in sorted(federated.namespaces):
            handle = federated.namespaces[name]
            wikis.append(
                {
                    "wiki_name": name,
                    "storage_dir": (
                        str(handle.storage_dir) if handle.storage_dir else None
                    ),
                    "kind": handle.kind,
                    "backend": handle.backend,
                    "origin": handle.origin,
                    "read_only": handle.read_only,
                    "description": handle.config.description,
                    "status": "ok",
                }
            )
        for skip in federated.skipped:
            wikis.append(
                {
                    "wiki_name": skip.name,
                    "storage_dir": None,
                    "origin": "namespace",
                    "read_only": True,
                    "status": skip.reason,
                    "detail": skip.detail,
                    "hint": skip.hint,
                }
            )
        return wikis

    async def get_wiki_info(
        self,
        wiki_name: str,
    ) -> dict[str, Any]:
        """Return metadata about a specific wiki.

        Args:
            wiki_name: Wiki name to describe.

        Returns:
            Dict with keys: wiki_name, storage_dir, source_count,
            search_weights, page_categories.
        """
        sources = await asyncio.to_thread(self._sources.list_sources)
        return {
            "wiki_name": wiki_name,
            "storage_dir": str(self._config.storage_dir),
            "source_count": len(sources),
            "search_weights": self._config.search_weights,
            "page_categories": [c.value for c in self._config.page_categories],
        }

    async def delete_wiki(
        self,
        wiki_name: str,
    ) -> dict[str, Any]:
        """Delete a wiki and all its data.

        This is a destructive operation — the storage directory is NOT
        removed; only the manifest and bookkeeping files are cleared.
        Physical file removal is left to the operator.

        Args:
            wiki_name: Wiki name to delete.

        Returns:
            Dict with keys: status, wiki_name, message.
        """
        self.logger.warning(
            "delete_wiki called for '%s' — clearing manifest only", wiki_name
        )
        # Remove all manifest entries
        for entry in await asyncio.to_thread(self._sources.list_sources):
            await asyncio.to_thread(self._sources.remove_source, entry.source_id)

        return {
            "status": "deleted",
            "wiki_name": wiki_name,
            "message": "Manifest cleared. Storage directory retained.",
        }

    # ------------------------------------------------------------------
    # Page Operations
    # ------------------------------------------------------------------

    async def browse_pages(
        self,
        wiki_name: str,
        category: Optional[str] = None,
        search: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Browse wiki pages, optionally filtered by category or search query.

        Args:
            wiki_name: Wiki name to browse.
            category: Optional category value to filter by (exact match).
            search: Optional search query — when given, results come
                from FTS ranking instead of the recency listing.

        Returns:
            List of page stub dicts (no bodies — use ``read_page``).
        """
        store = self._store_for(wiki_name)
        try:
            if search:
                return await store.search_fts(
                    search, category=category, limit=20
                )
            return await store.list_pages(category=category, limit=20)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("browse_pages failed: %s", exc)
            return []

    async def read_page(
        self,
        wiki_name: str,
        page_id: str,
        max_tokens: Optional[int] = None,
    ) -> dict[str, Any]:
        """Read the full content of a wiki page by its ID.

        Progressive disclosure: search returns compact stubs with each
        page's token cost; call this only for pages worth their tokens,
        optionally capping the spend with ``max_tokens``.

        Args:
            wiki_name: Wiki name containing the page.
            page_id: Stable ``concept_id`` of the page (a volatile
                PageIndex ``node_id`` is also accepted).
            max_tokens: Optional ceiling on returned content tokens —
                the body is deterministically truncated when over.

        Returns:
            Dict with keys: page_id, title, category, summary, content,
            token_count, truncated, source_id.  Returns
            ``{"error": "not_found"}`` when the page does not exist.
        """
        page = await self._store_for(wiki_name).get_page(page_id)
        if page is None:
            return {"error": "not_found", "page_id": page_id}
        content, truncated = truncate_to_tokens(
            page.get("body", ""), max_tokens
        )
        return {
            "page_id": page["concept_id"],
            "node_id": page.get("node_id"),
            "wiki_name": wiki_name,
            "title": page.get("title", ""),
            "category": page.get("category", ""),
            "summary": page.get("summary", ""),
            "content": content,
            "token_count": page.get("token_count", 0),
            "truncated": truncated,
            "source_id": page.get("source_id"),
        }

    async def create_page(
        self,
        wiki_name: str,
        title: str,
        content: str,
        category: str = "concept",
        related_pages: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Create a new wiki page with the given content.

        Inserts the page into the PageIndex tree and creates a corresponding
        WIKI_PAGE node in GraphIndex.

        Args:
            wiki_name: Wiki name to create the page in.
            title: Page title.
            content: Markdown content for the page.
            category: WikiPageCategory string value.
            related_pages: Optional list of related page IDs to link.

        Returns:
            Dict with keys: page_id, title, category, status.
        """
        # Markdown kept for the PageIndex authoring plane; the category
        # lives as a real column in the WikiStore (the HTML comment is
        # retained only for backwards compatibility of stored markdown).
        markdown = f"# {title}\n\n<!-- category: {category} -->\n\n{content}"

        page_id: Optional[str] = None
        if self._pi is None:
            # Composed without an authoring plane (the caller passed None
            # for ``pageindex_toolkit``). Say so plainly, instead of
            # letting the AttributeError fall into the except below and
            # surface as "'NoneType' object has no attribute
            # 'insert_markdown'" on every single page.
            self.logger.debug(
                "create_page: no PageIndexToolkit composed — writing to the "
                "WikiStore retrieval plane only (page id derived from the "
                "title, not a PageIndex node id)."
            )
        else:
            try:
                pi_result = await self._pi.insert_markdown(
                    wiki_name, markdown, doc_name=title
                )
                if isinstance(pi_result, dict):
                    # PageIndexToolkit.insert_markdown() contract:
                    # {"tree_name", "new_node_ids"}
                    new_ids = pi_result.get("new_node_ids") or []
                    page_id = str(new_ids[0]) if new_ids else None
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("create_page PageIndex insert failed: %s", exc)

        if not page_id:
            page_id = f"page-{title[:40].lower().replace(' ', '-')}"

        # Write to the WikiStore retrieval plane: category as a column,
        # body in the DB, related_pages as typed edges.
        try:
            record = WikiPageRecord(
                concept_id=page_id,
                node_id=page_id,
                title=title,
                category=category,
                summary=content[:300],
                body=content,
                token_count=estimate_tokens(content),
                origin="authored",
                asserted_by=f"agent:{self.agent_id}",
            )
            await self._store.upsert_pages([record])
            if related_pages:
                await self._store.add_edges(
                    [(page_id, str(rp), "references") for rp in related_pages]
                )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("create_page WikiStore upsert failed: %s", exc)

        # Optional GraphIndex mirror (off by default).
        if self._config.sync_graph:
            try:
                await self._gi.create_node(
                    kind="wiki_page",
                    title=title,
                    summary=content[:300],
                    domain_tags={"wiki": wiki_name, "category": category},
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "create_page GraphIndex create_node failed: %s", exc
                )

        await asyncio.to_thread(
            self._bookkeeper.log_operation,
            self._local_config_for(wiki_name).storage_dir,
            "CREATE_PAGE",
            f"title: {title!r}, category: {category}",
        )
        return {
            "page_id": page_id,
            "title": title,
            "category": category,
            "related_pages": list(related_pages or []),
            "status": "created",
        }

    async def update_page(
        self,
        wiki_name: str,
        page_id: str,
        content: str,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Update the content of an existing wiki page.

        Refreshes the WikiStore retrieval plane (row, FTS) so queries see
        the new content immediately, and best-effort re-inserts the
        markdown into the PageIndex authoring plane.

        Args:
            wiki_name: Wiki name containing the page.
            page_id: Node ID of the page to update.
            content: New Markdown content.
            reason: Optional reason for the update (logged).

        Returns:
            Dict with keys: page_id, status, reason. ``status`` is
            ``"not_found"`` when the page does not exist in the store.
        """
        existing = await self._store.get_page(page_id, include_body=False)
        if existing is None:
            return {"page_id": page_id, "status": "not_found", "reason": reason}

        # The WikiStore plane is the retrieval backend — update it first
        # so FTS/queries never go stale (the pre-fix behavior only wrote
        # the PageIndex tree, leaving this plane with the old body).
        record = WikiPageRecord(
            concept_id=existing["concept_id"],
            node_id=existing.get("node_id"),
            title=existing.get("title") or page_id,
            category=existing.get("category") or "concept",
            summary=content[:300],
            body=content,
            source_id=existing.get("source_id"),
            token_count=estimate_tokens(content),
            origin="authored",
            asserted_by=f"agent:{self.agent_id}",
        )
        await self._store.upsert_pages([record])

        try:
            await self._pi.insert_markdown(wiki_name, content, doc_name=page_id)
        except Exception as exc:  # noqa: BLE001
            self.logger.warning("update_page PageIndex insert failed: %s", exc)

        await asyncio.to_thread(
            self._bookkeeper.log_operation,
            self._local_config_for(wiki_name).storage_dir,
            "UPDATE_PAGE",
            f"page_id: {page_id}, reason: {reason!r}",
        )
        return {"page_id": page_id, "status": "updated", "reason": reason}

    async def remember(
        self,
        wiki_name: str,
        text: str,
        title: Optional[str] = None,
        category: str = "note",
        related_pages: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Save a fact, decision, or lesson into the wiki as durable memory.

        The page id is a deterministic hash of the title/text, so
        remembering the same thing twice updates the existing memory
        instead of duplicating it. Links to related pages are recorded
        as ``asserted`` edges.

        Args:
            wiki_name: Wiki to save the memory in.
            text: The knowledge to remember (markdown allowed).
            title: Optional short title; derived from the text when
                omitted.
            category: One of ``note``, ``decision``, ``lesson``,
                ``concept`` (open string).
            related_pages: Optional page ids to link the memory to.

        Returns:
            Dict with keys: page_id, title, category, status.
        """
        import hashlib

        title = (title or text.strip().splitlines()[0][:80]).strip()
        page_id = "mem-" + hashlib.sha1(
            f"{title}::{category}".encode("utf-8")
        ).hexdigest()[:12]

        existing = await self._store.get_page(page_id, include_body=False)
        record = WikiPageRecord(
            concept_id=page_id,
            node_id=page_id,
            title=title,
            category=category,
            summary=text[:300],
            body=text,
            token_count=estimate_tokens(text),
            origin="memory",
            asserted_by=f"agent:{self.agent_id}",
        )
        await self._store.upsert_pages([record])
        if related_pages:
            await self._store.add_edges(
                [(page_id, str(rp), "references", "asserted") for rp in related_pages]
            )

        await asyncio.to_thread(
            self._bookkeeper.log_operation,
            self._local_config_for(wiki_name).storage_dir,
            "REMEMBER",
            f"page_id: {page_id}, title: {title!r}, category: {category}",
        )
        return {
            "page_id": page_id,
            "title": title,
            "category": category,
            "status": "updated" if existing else "created",
        }

    async def delete_page(
        self,
        wiki_name: str,
        page_id: str,
    ) -> dict[str, Any]:
        """Delete a wiki page.

        Deletes the page from the WikiStore retrieval plane (row, FTS
        entry, embeddings, and edges) and best-effort removes the
        corresponding node from the PageIndex tree.

        Args:
            wiki_name: Wiki name containing the page.
            page_id: Stable ``concept_id`` (or PageIndex ``node_id``).

        Returns:
            Dict with keys: page_id, status, message.  ``status`` is
            ``"not_found"`` when the page does not exist.
        """
        page = await self._store.get_page(page_id, include_body=False)
        if page is None:
            return {
                "page_id": page_id,
                "status": "not_found",
                "message": "No such page in the wiki store.",
            }

        deleted = await self._store.delete_page(page["concept_id"])

        # Best-effort removal from the PageIndex authoring plane.
        node_id = page.get("node_id")
        if node_id:
            try:
                await self._pi.delete_node(wiki_name, node_id)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "delete_page: PageIndex delete_node(%s) failed: %s",
                    node_id,
                    exc,
                )

        await asyncio.to_thread(
            self._bookkeeper.log_operation,
            self._local_config_for(wiki_name).storage_dir,
            "DELETE_PAGE",
            f"page_id: {page['concept_id']}",
        )
        return {
            "page_id": page["concept_id"],
            "status": "deleted" if deleted else "not_found",
            "message": "Page removed from wiki store.",
        }

    # ------------------------------------------------------------------
    # Source Management
    # ------------------------------------------------------------------

    async def list_sources(
        self,
        wiki_name: str,
    ) -> list[dict[str, Any]]:
        """List all tracked raw sources for a wiki.

        Args:
            wiki_name: Wiki name to list sources for.

        Returns:
            List of source dicts (serialised :class:`SourceManifestEntry`).
        """
        sources = await asyncio.to_thread(self._sources.list_sources)
        return [e.model_dump() for e in sources]

    async def get_source_info(
        self,
        wiki_name: str,
        source_id: str,
    ) -> dict[str, Any]:
        """Get metadata for a single tracked source.

        Args:
            wiki_name: Wiki name.
            source_id: Stable source identifier.

        Returns:
            Source manifest entry dict, or ``{"error": "not_found"}`` when
            the source_id is unknown.
        """
        entry = await asyncio.to_thread(self._sources.get_source, source_id)
        if entry is None:
            return {"error": "not_found", "source_id": source_id}
        return entry.model_dump()

    async def reingest_source(
        self,
        wiki_name: str,
        source_id: str,
    ) -> dict[str, Any]:
        """Force re-ingest of a source regardless of staleness.

        Args:
            wiki_name: Wiki name.
            source_id: Stable source identifier to re-ingest.

        Returns:
            :class:`IngestReport` dict, or an error dict when the source
            is not tracked.
        """
        entry = await asyncio.to_thread(self._sources.get_source, source_id)
        if entry is None:
            return {"error": "not_found", "source_id": source_id}

        # Force staleness by removing the entry and re-adding
        await asyncio.to_thread(self._sources.remove_source, source_id)
        report = await self._ingest_orch.ingest(entry.source_uri, self._config)
        return report.model_dump()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        wiki_name: str,
        query: str,
        mode: str = "combined",
    ) -> list[dict[str, Any]]:
        """Search the wiki with a natural-language query.

        Args:
            wiki_name: Wiki name to search.
            query: Natural-language search query.
            mode: One of ``"combined"``, ``"pageindex"``, ``"graphindex"``.

        Returns:
            List of :class:`WikiSearchResult` dicts sorted by score (desc).
        """
        results = await self._search_for(wiki_name).search(
            query, mode=mode, top_k=15, tree_name=wiki_name
        )
        return [r.model_dump() for r in results]

    async def search_compact(
        self,
        wiki_name: str,
        query: str,
        budget_tokens: int = DEFAULT_BUDGET_TOKENS,
        mode: str = "combined",
    ) -> dict[str, Any]:
        """Search and return token-budgeted compact stubs (preferred).

        Each stub carries the page id, title, lead sentence, score, and
        the token cost of reading the full page — so the caller can
        decide what to ``read_page`` next without paying for bodies
        up front.

        Args:
            wiki_name: Wiki name to search.
            query: Natural-language search query.
            budget_tokens: Hard token ceiling for the packed context.
            mode: ``"combined"``, ``"lexical"``, or ``"vector"``.

        Returns:
            Dict with keys: context (packed text), stubs, tokens_used,
            results_packed, total_available, truncated.
        """
        results = await self._search_for(wiki_name).search(
            query, mode=mode, top_k=25, tree_name=wiki_name
        )
        packed = pack_results(results, budget_tokens=budget_tokens)
        return {
            "context": packed.text,
            "stubs": packed.stubs,
            "tokens_used": packed.tokens_used,
            "results_packed": packed.results_packed,
            "total_available": packed.total_available,
            "truncated": packed.truncated,
        }

    async def expand(
        self,
        wiki_name: str,
        page_id: str,
        rel: Optional[str] = None,
        budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    ) -> dict[str, Any]:
        """Progressively disclose a page's graph neighbourhood as stubs.

        Args:
            wiki_name: Wiki name.
            page_id: Seed page ``concept_id``.
            rel: Optional exact relation filter (e.g. ``"summarizes"``,
                ``"references"``).
            budget_tokens: Token ceiling for the packed stubs.

        Returns:
            Dict with keys: page_id, context, stubs, tokens_used,
            total_available, truncated.
        """
        neighbours = await self._store_for(wiki_name).neighbors(
            page_id, rel=rel
        )
        packed = pack_results(neighbours, budget_tokens=budget_tokens)
        return {
            "page_id": page_id,
            "context": packed.text,
            "stubs": packed.stubs,
            "tokens_used": packed.tokens_used,
            "total_available": packed.total_available,
            "truncated": packed.truncated,
        }

    async def find_related(
        self,
        wiki_name: str,
        page_id: str,
        depth: int = 2,
    ) -> list[dict[str, Any]]:
        """Find pages related to a given page via graph traversal.

        Args:
            wiki_name: Wiki name.
            page_id: GraphIndex node ID of the seed page.
            depth: Maximum traversal depth (hops).

        Returns:
            List of neighbour node dicts from GraphIndexToolkit.
        """
        return await self._search_for(wiki_name).find_related(
            page_id, depth=depth
        )

    # ------------------------------------------------------------------
    # OKF export boundary
    # ------------------------------------------------------------------

    async def export_okf(
        self,
        wiki_name: str,
        output_dir: str,
    ) -> dict[str, Any]:
        """Export the wiki as an OKF v0.1 markdown bundle (interchange).

        The wiki's internal store is machine-first SQLite; this tool
        lazily projects it into Open Knowledge Format — one markdown
        file per page with YAML frontmatter (``type`` from the page
        category, ``relates_to`` from the edges table), grouped in
        category directories with a root ``index.md``.

        Args:
            wiki_name: Wiki to export.
            output_dir: Destination directory for the bundle.

        Returns:
            Export report dict: files_written, categories,
            index_generated, output_dir.
        """
        from parrot.knowledge.wiki.export import export_okf_bundle

        self._config_for(wiki_name)
        report = await export_okf_bundle(
            self._store, Path(output_dir), wiki_name=wiki_name
        )
        await asyncio.to_thread(
            self._bookkeeper.log_operation,
            self._config.storage_dir,
            "EXPORT_OKF",
            f"output_dir: {output_dir}, files: {report.files_written}",
        )
        return report.model_dump()

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------

    async def get_index(self, wiki_name: str) -> str:
        """Return the current index.md content for a wiki.

        Args:
            wiki_name: Wiki name.

        Returns:
            Markdown string of the wiki's index.md, or an empty string
            when the file has not been generated yet.
        """
        storage_dir = self._config_for(wiki_name).storage_dir
        index_path = storage_dir / "index.md"
        if index_path.exists():
            return await asyncio.to_thread(index_path.read_text, encoding="utf-8")
        return ""

    async def get_log(self, wiki_name: str, last_n: int = 50) -> str:
        """Return the last ``last_n`` entries from log.md.

        Args:
            wiki_name: Wiki name.
            last_n: Maximum number of trailing log lines to return.

        Returns:
            String containing up to ``last_n`` log lines.
        """
        storage_dir = self._config_for(wiki_name).storage_dir
        return await asyncio.to_thread(
            self._bookkeeper.read_log, storage_dir, last_n=last_n
        )

    async def rebuild_index(self, wiki_name: str) -> dict[str, Any]:
        """Regenerate index.md from the current wiki state.

        Args:
            wiki_name: Wiki name.

        Returns:
            Dict with keys: status, wiki_name, index_length.
        """
        storage_dir = self._local_config_for(wiki_name).storage_dir
        sources = await asyncio.to_thread(self._sources.list_sources)
        content = await asyncio.to_thread(
            self._bookkeeper.rebuild_index,
            storage_dir,
            tree_name=wiki_name,
            sources=sources,
        )
        await asyncio.to_thread(
            self._bookkeeper.log_operation,
            storage_dir,
            "REBUILD_INDEX",
            f"sources: {len(sources)}, index_length: {len(content)}",
        )
        return {
            "status": "ok",
            "wiki_name": wiki_name,
            "index_length": len(content),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _local_config_for(self, wiki_name: str) -> WikiConfig:
        """Config for a WRITE, which may only ever target the local wiki.

        :meth:`_config_for` accepts federated namespace names because the
        read helpers dispatch on them. Writes do not dispatch — they all
        land on the local plane — so accepting a namespace name here
        would silently ingest another wiki's content into this one
        (FEAT-450 review).

        Args:
            wiki_name: Wiki name supplied by the caller.

        Returns:
            The configured :class:`WikiConfig`.

        Raises:
            ValueError: ``wiki_name`` is not the local wiki.
        """
        if wiki_name != self._config.wiki_name:
            hint = ""
            if self._is_namespace(wiki_name):
                hint = (
                    f" {wiki_name!r} is a read-only federated namespace; "
                    f"write to it with `wikitoolkit <command> --ns {wiki_name}`."
                )
            raise ValueError(
                f"Cannot write to wiki '{wiki_name}' through this toolkit "
                f"(configured for '{self._config.wiki_name}').{hint}"
            )
        return self._config

    def _config_for(self, wiki_name: str) -> WikiConfig:
        """Return the effective config for the requested wiki name.

        Validates that ``wiki_name`` names either the toolkit's configured
        wiki or one of the federated namespaces its injected store serves
        (FEAT-450). Anything else is an explicit programming error rather
        than a silent data-routing bug.

        The config object is per-toolkit, so a namespace resolves to the
        SAME config — namespace dispatch is a *store* concern, handled by
        :meth:`_store_for` / :meth:`_search_for`.

        Args:
            wiki_name: Wiki name to look up.

        Returns:
            The configured :class:`WikiConfig`.

        Raises:
            ValueError: When ``wiki_name`` does not match the configured wiki.
        """
        if wiki_name != self._config.wiki_name and not self._is_namespace(
            wiki_name
        ):
            known = ""
            federated = self._federated
            if federated is not None and federated.namespaces:
                known = (
                    " Federated namespaces: "
                    + ", ".join(sorted(federated.namespaces))
                    + "."
                )
            raise ValueError(
                f"Wiki '{wiki_name}' is not managed by this toolkit "
                f"(configured for '{self._config.wiki_name}').{known} "
                "Construct a separate LLMWikiToolkit for each wiki instance."
            )
        return self._config

    def _synthesise_answer(
        self,
        question: str,
        packed_context: str,
    ) -> str:
        """Synthesise an answer from token-budgeted packed context.

        This is a lightweight placeholder: it returns the packed stub
        block with an attribution header.  In production, replace with
        an LLM completion call using the bot's configured adapter — the
        packed context is already budgeted for direct prompt inclusion.

        Args:
            question: The original question.
            packed_context: Compact stub block from :func:`pack_results`.

        Returns:
            A synthesised answer string.
        """
        if not packed_context:
            return (
                f"No relevant wiki pages found for: {question!r}. "
                "Try ingesting more sources first."
            )
        return f"Based on the wiki knowledge base:\n\n{packed_context}"
