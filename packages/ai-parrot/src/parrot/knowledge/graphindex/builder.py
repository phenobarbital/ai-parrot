"""Pipeline Builder — GraphIndexBuilder Orchestrator.

``GraphIndexBuilder`` wires together all 6 GraphIndex pipeline stages:

1. Extraction — CodeExtractor, LoaderExtractor, SkillExtractor run concurrently
2. Embedding — GraphIndexEmbedder (FAISS index construction)
3. Graph assembly — GraphAssembler (rustworkx PyDiGraph)
4. Cross-domain resolution — resolve_cross_domain (inferred edges)
5. Persistence — GraphIndexPersistence (ArangoDB + pgvector)
6. Analytics + Report — compute_analytics + generate_report

Entry points:
- ``build(sources, ctx)`` — full reindex
- ``ingest_document(uri, ctx)`` — incremental per-document refresh
- ``regenerate_report(ctx)`` — on-demand report refresh (lazy/explicit)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional, Type

import pathspec

from parrot.knowledge.graphindex.analytics import compute_analytics, generate_report
from parrot.knowledge.graphindex.assemble import GraphAssembler
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder
from parrot.knowledge.graphindex.extractors.code import CodeExtractor
from parrot.knowledge.graphindex.extractors.loader import LoaderExtractor
from parrot.knowledge.graphindex.extractors.skill import SkillExtractor
from parrot.knowledge.graphindex.persist import GraphIndexPersistence
from parrot.knowledge.graphindex.resolve import ResolutionConfig, resolve_cross_domain
from parrot.knowledge.graphindex.schema import (
    BuildResult,
    IngestResult,
    Provenance,
    SourceConfig,
    UniversalEdge,
    UniversalNode,
)
from parrot.knowledge.graphindex.communities import (
    CommunitiesResult,
    detect_communities,
)
from parrot.knowledge.graphindex.signals import SignalRelevanceConfig
from parrot.knowledge.ontology.schema import TenantContext
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

logger = logging.getLogger(__name__)


class GraphIndexBuilder:
    """Orchestrates the full GraphIndex pipeline.

    Wires together extraction, embedding, assembly, resolution,
    persistence, and analytics into :meth:`build` and
    :meth:`ingest_document` flows.

    Args:
        persistence: An initialised ``GraphIndexPersistence`` instance.
        embedder: An initialised ``GraphIndexEmbedder`` instance.
        output_dir: Directory for generated reports and other artefacts.
        ignore_file: Optional path to a ``.graphindexignore`` file.
        resolution_config: Optional ``ResolutionConfig`` for cross-domain
            resolution threshold and caps.
        pageindex_toolkit: Optional :class:`PageIndexToolkit`. When set,
            hierarchical loader sources are persisted as PageIndex trees
            (lean ToC + per-node markdown sidecars) and the resulting
            ``UniversalNode`` Section instances carry a ``content_ref``
            that resolves to the body via :class:`NodeContentStore`.
            The toolkit's tree name is exposed on the ``Document``
            UniversalNode as ``domain_tags['pageindex_tree_id']`` so
            the ontology's ``search_documents_scoped`` routing has a
            concrete target. Omit to keep the legacy in-memory path
            with no sidecar persistence.
        signal_config: Optional :class:`SignalRelevanceConfig` (FEAT-190).
            Stored only; the builder does not invoke the signal
            scorer itself. Downstream consumers (analytics report,
            FEAT-192 toolkit, the LLM-Wiki orchestrator) read this
            attribute when they need to score node relevance with
            tenant-specific weights instead of library defaults.
        detect_communities_enabled: When True, run FEAT-191 Louvain
            community detection between resolve and persist; the
            partition is stored on ``self.last_community_result``
            and ``community_id`` is written into every node's
            ``domain_tags`` so it round-trips through persistence.
            Default False — opt-in.
        community_resolution: Louvain γ resolution parameter
            (>1.0 finds smaller/tighter communities).
        code_extractor_class: The ``CodeExtractor`` subclass to use for
            Python source files (FEAT-240). Defaults to ``CodeExtractor``.
            Pass ``OdooCodeExtractor`` to enable Odoo model extraction.
        export_html_enabled: When True and ``output_dir`` is set, emit an
            interactive ``graph.html`` map plus a serialized ``graph.json``
            after analytics. Communities colour the nodes and god nodes are
            sized/highlighted, so pairing this with
            ``detect_communities_enabled=True`` yields the richest map.
            Default False — opt-in.
    """

    def __init__(
        self,
        persistence: GraphIndexPersistence,
        embedder: GraphIndexEmbedder,
        output_dir: Optional[Path] = None,
        ignore_file: Optional[Path] = None,
        resolution_config: Optional[ResolutionConfig] = None,
        pageindex_toolkit: Optional[PageIndexToolkit] = None,
        signal_config: Optional[SignalRelevanceConfig] = None,
        detect_communities_enabled: bool = False,
        community_resolution: float = 1.0,
        code_extractor_class: Type = CodeExtractor,
        export_html_enabled: bool = False,
    ) -> None:
        self.persistence = persistence
        self.embedder = embedder
        self._code_extractor_class = code_extractor_class
        self.output_dir = Path(output_dir) if output_dir is not None else None
        self.resolution_config = resolution_config or ResolutionConfig()
        self.pageindex_toolkit = pageindex_toolkit
        self.signal_config = signal_config
        self.detect_communities_enabled = detect_communities_enabled
        self.community_resolution = community_resolution
        self.export_html_enabled = export_html_enabled
        self.last_community_result: Optional[CommunitiesResult] = None
        self.logger = logging.getLogger(__name__)
        self._ignore_spec: Optional[pathspec.PathSpec] = self._load_ignore(ignore_file)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def build(self, sources: SourceConfig, ctx: TenantContext) -> BuildResult:
        """Full reindex: run all 6 stages in sequence.

        Extractors run concurrently (stage 1 via ``asyncio.gather``).
        Stages 2-6 run sequentially.

        Args:
            sources: Source configuration describing what to index.
            ctx: Tenant context for ArangoDB and pgvector namespacing.

        Returns:
            ``BuildResult`` with node/edge counts and optional report path.
        """
        errors: list[str] = []

        # Stage 1: Extract concurrently
        try:
            code_result, loader_result, skill_result = await asyncio.gather(
                self._extract_code(sources),
                self._extract_loaders(sources),
                self._extract_skills(sources),
            )
        except Exception as exc:
            logger.error("Extraction stage failed: %s", exc)
            errors.append(f"Extraction failed: {exc}")
            code_result = ([], [])
            loader_result = ([], [])
            skill_result = ([], [])

        all_nodes: list[UniversalNode] = (
            code_result[0] + loader_result[0] + skill_result[0]
        )
        all_edges: list[UniversalEdge] = (
            code_result[1] + loader_result[1] + skill_result[1]
        )
        logger.info("Stage 1 complete: %d nodes, %d edges", len(all_nodes), len(all_edges))

        # Stage 2: Embed
        try:
            all_nodes = await self.embedder.embed_nodes(all_nodes)
            logger.info("Stage 2 complete: embeddings generated for %d nodes", len(all_nodes))
        except Exception as exc:
            logger.error("Embedding stage failed: %s", exc)
            errors.append(f"Embedding failed: {exc}")

        # Stage 3: Assemble graph
        assembler = GraphAssembler(tenant_id=ctx.tenant_id)
        assembler.add_nodes(all_nodes)
        assembler.add_edges(all_edges)
        logger.info(
            "Stage 3 complete: graph has %d nodes, %d edges",
            assembler.node_count,
            assembler.edge_count,
        )

        # Stage 4: Cross-domain resolution
        try:
            inferred_edges = await resolve_cross_domain(
                all_nodes, self.embedder, self.resolution_config
            )
            assembler.add_edges(inferred_edges)
            all_edges = all_edges + inferred_edges
            logger.info("Stage 4 complete: %d inferred edges", len(inferred_edges))
        except Exception as exc:
            logger.error("Resolution stage failed: %s", exc)
            errors.append(f"Resolution failed: {exc}")
            inferred_edges = []

        # Stage 4.5: Louvain community detection (FEAT-191, opt-in).
        # Runs between resolve and persist so the community_id rides
        # along on UniversalNode.domain_tags to ArangoDB.
        if self.detect_communities_enabled:
            try:
                self.last_community_result = detect_communities(
                    graph=assembler.graph,
                    nodes=all_nodes,
                    resolution=self.community_resolution,
                    signal_config=self.signal_config,
                    embedder=self.embedder if self.signal_config else None,
                    write_back_to_nodes=True,
                )
                logger.info(
                    "Stage 4.5 complete: %d communities, modularity=%.4f",
                    len(self.last_community_result.communities),
                    self.last_community_result.modularity,
                )
            except Exception as exc:
                logger.error("Community detection failed: %s", exc)
                errors.append(f"Community detection failed: {exc}")

        # Stage 5: Persist
        try:
            persist_result = await self.persistence.persist_graph(ctx, all_nodes, all_edges)
            logger.info("Stage 5 complete: %s", persist_result)
        except Exception as exc:
            logger.error("Persistence stage failed: %s", exc)
            errors.append(f"Persistence failed: {exc}")
            persist_result = {"nodes_persisted": 0, "edges_persisted": 0}

        # Stage 6: Analytics + Report
        report_path: Optional[Path] = None
        analytics = None
        try:
            analytics = compute_analytics(assembler.graph, all_nodes, all_edges)
            # Attach FEAT-191 partition so the report includes communities.
            analytics.communities = self.last_community_result
            if self.output_dir is not None:
                report_path = generate_report(
                    analytics, self.output_dir, tenant_id=ctx.tenant_id
                )
                logger.info("Stage 6 complete: report written to %s", report_path)
            else:
                logger.info("Stage 6 complete: no output_dir, report generation skipped")
        except Exception as exc:
            logger.error("Analytics stage failed: %s", exc)
            errors.append(f"Analytics failed: {exc}")

        # Stage 6.5: OKF Projection — project per-node .md sidecars (FEAT-239)
        projection_report = None
        if self.output_dir is not None:
            try:
                # Deferred import: projection imports from schema (which imports
                # from analytics), creating a cycle if imported at module level.
                from parrot.knowledge.graphindex.projection import (  # noqa: PLC0415
                    project_graph_sidecars,
                )

                content_store = getattr(self.pageindex_toolkit, "_content_store", None)
                projection_report = await project_graph_sidecars(
                    all_nodes,
                    all_edges,
                    self.output_dir,
                    content_store=content_store,
                )
                # Record whether the analytics report also received frontmatter
                # (Stage 6 ran successfully and wrote GRAPH_REPORT.md).
                projection_report.report_frontmatter_added = report_path is not None
                logger.info(
                    "Stage 6.5 complete: %d nodes projected",
                    projection_report.nodes_projected,
                )
            except Exception as exc:
                logger.error("Projection stage failed: %s", exc)
                errors.append(f"Projection failed: {exc}")

        # Stage 6.6: Interactive HTML map — emit graph.html + graph.json.
        graph_html_path: Optional[Path] = None
        graph_json_path: Optional[Path] = None
        if self.export_html_enabled and self.output_dir is not None:
            try:
                # Deferred import: export_html is optional and keeps the
                # builder importable when its (light) deps are absent.
                from parrot.knowledge.graphindex.export_html import (  # noqa: PLC0415
                    export_graph,
                )

                graph_html_path, graph_json_path = export_graph(
                    assembler.graph,
                    self.output_dir,
                    communities=self.last_community_result,
                    analytics=analytics,
                )
                logger.info(
                    "Stage 6.6 complete: interactive map written to %s",
                    graph_html_path,
                )
            except Exception as exc:
                logger.error("HTML export stage failed: %s", exc)
                errors.append(f"HTML export failed: {exc}")

        inferred_count = sum(
            1 for e in all_edges if e.provenance == Provenance.INFERRED
        )
        return BuildResult(
            tenant_id=ctx.tenant_id,
            node_count=persist_result.get("nodes_persisted", len(all_nodes)),
            edge_count=persist_result.get("edges_persisted", len(all_edges)),
            inferred_edge_count=inferred_count,
            report_path=report_path,
            errors=errors,
            projection_report=projection_report,
            graph_html_path=graph_html_path,
            graph_json_path=graph_json_path,
        )

    async def ingest_document(self, uri: str, ctx: TenantContext) -> IngestResult:
        """Incremental per-document refresh.

        Re-runs extraction stages for the given document URI only.
        Replaces the document's slice in ArangoDB atomically via
        ``GraphIndexPersistence.replace_document_slice``.

        Report is NOT regenerated automatically — call
        ``regenerate_report(ctx)`` explicitly if needed.

        Args:
            uri: URI of the document to reprocess.
            ctx: Tenant context.

        Returns:
            ``IngestResult`` with replacement counts.
        """
        errors: list[str] = []
        nodes: list[UniversalNode] = []
        edges: list[UniversalEdge] = []

        # Re-run extraction for this document
        try:
            # Try each extractor and collect results for this URI
            code_nodes, code_edges = await self._extract_code_for_uri(uri)
            loader_nodes, loader_edges = await self._extract_loader_for_uri(uri)
            skill_nodes, skill_edges = await self._extract_skill_for_uri(uri)
            nodes = code_nodes + loader_nodes + skill_nodes
            edges = code_edges + loader_edges + skill_edges
        except Exception as exc:
            logger.error("Extraction failed for document %s: %s", uri, exc)
            errors.append(f"Extraction failed: {exc}")

        # Embed new nodes
        try:
            nodes = await self.embedder.embed_nodes(nodes)
        except Exception as exc:
            logger.error("Embedding failed for document %s: %s", uri, exc)
            errors.append(f"Embedding failed: {exc}")

        # Atomic replace via persistence
        try:
            replace_result = await self.persistence.replace_document_slice(
                ctx, uri, nodes, edges
            )
            logger.info("Ingested document %s: %s", uri, replace_result)
        except Exception as exc:
            logger.error("Replace slice failed for document %s: %s", uri, exc)
            errors.append(f"Replace failed: {exc}")
            replace_result = {"nodes_replaced": 0, "edges_replaced": 0}

        return IngestResult(
            tenant_id=ctx.tenant_id,
            document_uri=uri,
            nodes_replaced=replace_result.get("nodes_replaced", 0),
            edges_replaced=replace_result.get("edges_replaced", 0),
            errors=errors,
        )

    async def regenerate_report(self, ctx: TenantContext) -> Path:
        """On-demand report refresh from current graph state.

        This method is intentionally lazy and explicit — it is NOT
        triggered automatically by ``ingest_document``.

        Args:
            ctx: Tenant context (used to scope persisted data retrieval and
                the frontmatter resource URI in GRAPH_REPORT.md).

        Returns:
            Path to the generated ``GRAPH_REPORT.md``.

        Raises:
            ValueError: If the builder was constructed without an
                ``output_dir`` — there is nowhere to write the report.
        """
        if self.output_dir is None:
            raise ValueError(
                "regenerate_report() requires output_dir to be set on the builder."
            )
        # Build an in-memory assembler from the persisted graph state.
        # For now, generate an empty analytics result (full reload from ArangoDB
        # is planned for a future task — this satisfies the explicit call contract).
        from parrot.knowledge.graphindex.analytics import AnalyticsResult  # noqa: PLC0415

        analytics = AnalyticsResult()
        report_path = generate_report(analytics, self.output_dir, tenant_id=ctx.tenant_id)
        logger.info("regenerate_report: written to %s", report_path)
        return report_path

    # ------------------------------------------------------------------
    # Private helpers — extraction
    # ------------------------------------------------------------------

    def _load_ignore(self, ignore_file: Optional[Path]) -> Optional[pathspec.PathSpec]:
        """Load ``.graphindexignore`` patterns from a file.

        Args:
            ignore_file: Path to the ignore file.

        Returns:
            Compiled ``PathSpec``, or ``None`` if the file does not exist.
        """
        if ignore_file is None:
            return None
        ignore_path = Path(ignore_file)
        if not ignore_path.exists():
            return None
        lines = ignore_path.read_text(encoding="utf-8").splitlines()
        return pathspec.PathSpec.from_lines("gitwildmatch", lines)

    def _is_ignored(self, path: str) -> bool:
        """Check whether a path matches the ignore spec.

        Args:
            path: File path string to check.

        Returns:
            ``True`` if the path should be excluded from indexing.
        """
        if self._ignore_spec is None:
            return False
        return self._ignore_spec.match_file(path)

    async def _extract_code(
        self, sources: SourceConfig
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Extract nodes and edges from all configured code paths.

        Args:
            sources: Source configuration.

        Returns:
            Tuple of (nodes, edges).
        """
        nodes: list[UniversalNode] = []
        edges: list[UniversalEdge] = []
        extractor = self._code_extractor_class()
        for path_str in sources.code_paths:
            if self._is_ignored(path_str):
                logger.debug("Ignoring code path: %s", path_str)
                continue
            try:
                p = Path(path_str)
                if p.is_file():
                    files = [p]
                else:
                    files = list(p.rglob("*.py"))
                for f in files:
                    if self._is_ignored(str(f)):
                        continue
                    try:
                        mtime = os.stat(f).st_mtime
                        source = f.read_text(encoding="utf-8", errors="replace")
                        # Incremental staleness check (FEAT-240): skip unchanged files
                        if hasattr(self.persistence, "is_stale"):
                            sha1 = hashlib.sha1(
                                source.encode("utf-8", errors="replace")
                            ).hexdigest()
                            if not await self.persistence.is_stale(
                                sources.ctx if hasattr(sources, "ctx") else None,
                                str(f),
                                mtime,
                                sha1,
                            ):
                                logger.debug("Skipping unchanged file: %s", f)
                                continue
                        n, e = await extractor.extract(str(f), source, mtime=mtime)
                        nodes.extend(n)
                        edges.extend(e)
                    except Exception as exc:
                        logger.warning("Failed to extract %s: %s", f, exc)
            except Exception as exc:
                logger.error("Code extraction failed for %s: %s", path_str, exc)
        return nodes, edges

    async def _extract_loaders(
        self, sources: SourceConfig
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Extract nodes and edges from loader sources.

        Args:
            sources: Source configuration.

        Returns:
            Tuple of (nodes, edges).
        """
        nodes: list[UniversalNode] = []
        edges: list[UniversalEdge] = []
        extractor = LoaderExtractor(toolkit=self.pageindex_toolkit)
        for uri in sources.loader_sources:
            if self._is_ignored(uri):
                logger.debug("Ignoring loader source: %s", uri)
                continue
            try:
                # For each URI, create a minimal loader and extract
                # The loader is passed as a source string; LoaderExtractor
                # accepts a loader instance and a source string.
                # For the builder we create a placeholder that passes the URI.
                n, e = await extractor.extract(None, uri)
                nodes.extend(n)
                edges.extend(e)
            except Exception as exc:
                logger.warning("Failed to extract loader source %s: %s", uri, exc)
        return nodes, edges

    async def _extract_skills(
        self, sources: SourceConfig
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Extract nodes and edges from skill paths.

        Args:
            sources: Source configuration.

        Returns:
            Tuple of (nodes, edges).
        """
        nodes: list[UniversalNode] = []
        edges: list[UniversalEdge] = []
        extractor = SkillExtractor()
        for path_str in sources.skill_paths:
            if self._is_ignored(path_str):
                logger.debug("Ignoring skill path: %s", path_str)
                continue
            try:
                p = Path(path_str)
                if p.is_file():
                    files = [p]
                else:
                    files = list(p.rglob("*.md"))
                for f in files:
                    if self._is_ignored(str(f)):
                        continue
                    try:
                        content = f.read_text(encoding="utf-8", errors="replace")
                        n, e = await extractor.extract(str(f), content)
                        nodes.extend(n)
                        edges.extend(e)
                    except Exception as exc:
                        logger.warning("Failed to extract skill %s: %s", f, exc)
            except Exception as exc:
                logger.error("Skill extraction failed for %s: %s", path_str, exc)
        return nodes, edges

    # Incremental extraction helpers — single URI/file

    async def _extract_code_for_uri(
        self, uri: str
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Extract code nodes for a single URI (incremental).

        Args:
            uri: File path URI.

        Returns:
            Tuple of (nodes, edges), empty if not a Python file.
        """
        if not uri.endswith(".py"):
            return [], []
        if self._is_ignored(uri):
            return [], []
        try:
            extractor = self._code_extractor_class()
            f = Path(uri)
            mtime = os.stat(f).st_mtime
            source = f.read_text(encoding="utf-8", errors="replace")
            return await extractor.extract(uri, source, mtime=mtime)
        except Exception as exc:
            logger.warning("Code extraction for %s failed: %s", uri, exc)
            return [], []

    async def _extract_loader_for_uri(
        self, uri: str
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Extract loader nodes for a single URI (incremental).

        Args:
            uri: Document URI.

        Returns:
            Tuple of (nodes, edges).
        """
        if self._is_ignored(uri):
            return [], []
        try:
            extractor = LoaderExtractor(toolkit=self.pageindex_toolkit)
            return await extractor.extract(None, uri)
        except Exception as exc:
            logger.warning("Loader extraction for %s failed: %s", uri, exc)
            return [], []

    async def _extract_skill_for_uri(
        self, uri: str
    ) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Extract skill nodes for a single URI (incremental).

        Args:
            uri: File path URI.

        Returns:
            Tuple of (nodes, edges), empty if not a Markdown file.
        """
        if not uri.endswith(".md"):
            return [], []
        if self._is_ignored(uri):
            return [], []
        try:
            extractor = SkillExtractor()
            content = Path(uri).read_text(encoding="utf-8", errors="replace")
            return await extractor.extract(uri, content)
        except Exception as exc:
            logger.warning("Skill extraction for %s failed: %s", uri, exc)
            return [], []
