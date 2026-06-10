"""GraphIndexLoader — :class:`AbstractLoader` wrapper around GraphIndex.

This loader accepts a list of files and runs the **full**
:class:`~parrot.knowledge.graphindex.builder.GraphIndexBuilder` pipeline
(extract → embed → assemble → cross-domain resolve → analytics) over them,
emitting ``UniversalNode`` / ``UniversalEdge`` that are compatible with the rest
of the GraphIndex subsystem.

ArangoDB persistence is **optional**:

* When ArangoDB credentials are supplied (explicit kwargs or an ``arango``
  dict; missing fields are filled from ``ARANGODB_*`` env vars via
  ``navconfig``), the graph is persisted through
  :class:`~parrot.knowledge.graphindex.persist.GraphIndexPersistence` backed by
  an :class:`~parrot.knowledge.ontology.graph_store.OntologyGraphStore`.
* When no credentials are given, an in-process no-op persistence is used: the
  full pipeline still runs and the assembled graph is exposed in memory, but
  nothing is written to a database.

As with :class:`PageIndexLoader`, two views are offered: ``load()`` returns one
:class:`~parrot.stores.models.Document` per graph node, while
:meth:`build_graph` / the :pyattr:`nodes`, :pyattr:`edges`, :pyattr:`build_result`
attributes expose the native artifacts.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, List, Optional, Union

from parrot.loaders.abstract import AbstractLoader
from parrot.stores.models import Document

from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.schema import TenantContext

from .builder import GraphIndexBuilder
from .embed import GraphIndexEmbedder
from .meta_ontology import build_graphindex_ontology
from .persist import GraphIndexPersistence
from .schema import BuildResult, SourceConfig, UniversalEdge, UniversalNode


class _NullPersistence:
    """No-op persistence used when no ArangoDB credentials are supplied.

    Mirrors the :class:`GraphIndexPersistence` surface the builder calls so the
    full pipeline runs end-to-end without a database. Nothing is written.
    """

    async def persist_graph(
        self,
        ctx: TenantContext,
        nodes: list,
        edges: list,
    ) -> dict:
        return {"nodes_persisted": 0, "edges_persisted": 0}

    async def replace_document_slice(
        self,
        ctx: TenantContext,
        document_uri: str,
        nodes: list,
        edges: list,
    ) -> dict:
        return {"nodes_replaced": 0, "edges_replaced": 0}


class _CapturingPersistence:
    """Decorator that records the assembled nodes/edges then delegates.

    The builder hands the fully-resolved node/edge lists (including inferred
    edges) to ``persist_graph``. Wrapping the real or null persistence lets the
    loader recover those lists from a single ``build()`` run — without
    re-extracting — to project them into :class:`Document` objects.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.nodes: list[UniversalNode] = []
        self.edges: list[UniversalEdge] = []

    async def persist_graph(self, ctx, nodes, edges):  # noqa: ANN001
        self.nodes = list(nodes)
        self.edges = list(edges)
        return await self._inner.persist_graph(ctx, nodes, edges)

    async def replace_document_slice(self, ctx, document_uri, nodes, edges):  # noqa: ANN001
        self.nodes = list(nodes)
        self.edges = list(edges)
        return await self._inner.replace_document_slice(
            ctx, document_uri, nodes, edges
        )


class GraphIndexLoader(AbstractLoader):
    """Build a GraphIndex graph from a list of files.

    Args:
        source: Path, directory, or list of paths to index.
        tenant_id: Tenant identifier used for graph isolation and the default
            ArangoDB database / pgvector schema names.
        client: An ``AbstractClient`` for the optional PageIndex adapter used
            when ``storage_dir`` is set (hierarchical content → sidecars). When
            ``None`` and an adapter is needed, a default client is created.
        model: Model id for that adapter.
        adapter: A pre-built ``PageIndexLLMAdapter`` (overrides ``client``).
        output_dir: Directory for the generated ``GRAPH_REPORT.md``. A temp
            directory is used when omitted.
        embedding_model: Embedding model name (via ``EmbeddingRegistry``).
        embedding_dim: Embedding dimension (must match the model output).
        pgvector_dsn: Optional DSN for durable pgvector embedding storage. When
            ``None`` only the in-memory FAISS index is built.
        detect_communities: Enable Louvain community detection.
        arango: ArangoDB connection dict (alternative to discrete kwargs).
        arango_host / arango_port / arango_protocol / arango_user /
        arango_password / arango_database: Discrete ArangoDB credentials.
            Supplying ``arango`` or **any** of these enables persistence; the
            rest are filled from ``ARANGODB_*`` env vars.
        storage_dir: When set (and an adapter is available), a
            :class:`PageIndexToolkit` is attached so hierarchical documents are
            persisted as PageIndex trees with per-node sidecars.
        **kwargs: Forwarded to :class:`AbstractLoader`.
    """

    extensions: List[str] = [
        '.pdf', '.md', '.markdown', '.txt', '.text', '.html', '.htm', '.docx',
    ]

    def __init__(
        self,
        source: Optional[Union[str, Path, List[Union[str, Path]]]] = None,
        *,
        tenant_id: str = "default",
        client: Any = None,
        model: Optional[str] = None,
        adapter: Any = None,
        output_dir: Optional[Union[str, Path]] = None,
        embedding_model: str = "default",
        embedding_dim: int = 384,
        pgvector_dsn: Optional[str] = None,
        detect_communities: bool = False,
        arango: Optional[dict] = None,
        arango_host: Optional[str] = None,
        arango_port: Optional[int] = None,
        arango_protocol: Optional[str] = None,
        arango_user: Optional[str] = None,
        arango_password: Optional[str] = None,
        arango_database: Optional[str] = None,
        storage_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(source, **kwargs)
        self.doctype = 'graphindex_node'
        self.tenant_id = tenant_id
        self.detect_communities = detect_communities
        self._output_dir = Path(output_dir) if output_dir is not None else None

        # Optional PageIndex adapter + toolkit (only for hierarchical content).
        self._pageindex_toolkit = None
        self._adapter = adapter
        if storage_dir is not None:
            from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
            from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

            if self._adapter is None:
                if client is None:
                    client = self.get_default_llm(model=model)
                self._adapter = PageIndexLLMAdapter(client=client, model=model)
            self._pageindex_toolkit = PageIndexToolkit(self._adapter, storage_dir)

        self.embedder = GraphIndexEmbedder(
            model_name=embedding_model,
            dimension=embedding_dim,
            pgvector_dsn=pgvector_dsn,
        )

        # Resolve ArangoDB credentials → persistence enabled iff explicit.
        self._arango_params = self._resolve_arango(
            arango,
            arango_host,
            arango_port,
            arango_protocol,
            arango_user,
            arango_password,
            arango_database,
        )
        self.persist_enabled = self._arango_params is not None
        self.arango_db = (
            arango_database
            or (self._arango_params or {}).get("database")
            or f"db_{tenant_id}"
        )

        # The GraphIndex meta-ontology defines the ``gi_*`` vertex/edge
        # collections; using it as the tenant ontology means
        # ``initialize_tenant`` provisions exactly the collections persistence
        # routes into.
        self._ontology = build_graphindex_ontology()
        self.ctx = TenantContext(
            tenant_id=tenant_id,
            arango_db=self.arango_db,
            pgvector_schema=f"schema_{tenant_id}",
            ontology=self._ontology,
        )

        # Native artifacts populated by build_graph()/load().
        self.build_result: Optional[BuildResult] = None
        self.nodes: List[UniversalNode] = []
        self.edges: List[UniversalEdge] = []
        self.graph_store: Optional[OntologyGraphStore] = None
        self.builder: Optional[GraphIndexBuilder] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def load(  # type: ignore[override]
        self,
        source: Optional[Any] = None,
        split_documents: bool = False,
        **kwargs: Any,
    ) -> List[Document]:
        """Run the pipeline and return one Document per graph node.

        Args:
            source: Override for the construction-time source.
            split_documents: Re-chunk node Documents. Off by default — graph
                nodes already carry summaries.
            **kwargs: Accepted for signature compatibility; ignored.

        Returns:
            One :class:`Document` per :class:`UniversalNode`.
        """
        await self.build_graph(source)
        return [self._node_to_document(node) for node in self.nodes]

    async def build_graph(self, source: Optional[Any] = None) -> BuildResult:
        """Run the full GraphIndex pipeline and return the :class:`BuildResult`.

        Side effects: persists to ArangoDB when credentials were supplied, and
        populates :pyattr:`nodes`, :pyattr:`edges`, :pyattr:`build_result`.

        Args:
            source: Optional override for the construction-time source.

        Returns:
            The pipeline :class:`BuildResult` (persisted counts + report path).
        """
        files = self._resolve_files(source)
        inner = await self._make_persistence()
        capture = _CapturingPersistence(inner)
        output_dir = self._output_dir or Path(
            tempfile.mkdtemp(prefix="graphindex_")
        )
        self.builder = GraphIndexBuilder(
            persistence=capture,
            embedder=self.embedder,
            output_dir=output_dir,
            pageindex_toolkit=self._pageindex_toolkit,
            detect_communities_enabled=self.detect_communities,
        )
        sources = SourceConfig(
            tenant_id=self.tenant_id,
            loader_sources=[str(f) for f in files],
        )
        result = await self.builder.build(sources, self.ctx)
        self.build_result = result
        self.nodes = capture.nodes
        self.edges = capture.edges
        return result

    # ------------------------------------------------------------------
    # AbstractLoader hook (single file) — kept for ABC + base-class reuse
    # ------------------------------------------------------------------

    async def _load(self, source: Union[str, Path], **kwargs: Any) -> List[Document]:
        """Build a single-file graph and return its node Documents."""
        await self.build_graph([source])
        return [self._node_to_document(node) for node in self.nodes]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _make_persistence(self) -> Any:
        """Build the persistence target (real ArangoDB or in-memory no-op)."""
        if not self.persist_enabled:
            return _NullPersistence()

        from asyncdb import AsyncDB

        db = AsyncDB("arangodb", params=self._arango_params)
        try:
            await db.connection()
        except Exception as exc:  # pragma: no cover - needs a live server
            self.logger.error("ArangoDB connection failed: %s", exc)
            raise
        self.graph_store = OntologyGraphStore(arango_client=db)
        try:
            await self.graph_store.initialize_tenant(self.ctx)
        except Exception as exc:  # pragma: no cover - needs a live server
            self.logger.warning(
                "initialize_tenant failed (collections may already exist): %s",
                exc,
            )
        return GraphIndexPersistence(self.graph_store)

    def _resolve_arango(
        self,
        arango: Optional[dict],
        host: Optional[str],
        port: Optional[int],
        protocol: Optional[str],
        user: Optional[str],
        password: Optional[str],
        database: Optional[str],
    ) -> Optional[dict]:
        """Resolve ArangoDB connection params, or ``None`` when not requested.

        Persistence is enabled only when the caller explicitly passed an
        ``arango`` dict or any discrete credential. Missing fields fall back to
        ``ARANGODB_*`` environment variables.
        """
        explicit = arango is not None or any(
            v is not None for v in (host, user, password, database)
        )
        if not explicit:
            return None

        from navconfig import config  # local import: optional dependency

        def _cfg(key: str, default: Any) -> Any:
            # navconfig's config.get may return None for a missing key even
            # when a fallback is passed, so coalesce explicitly.
            val = config.get(key)
            return val if val is not None else default

        base = dict(arango) if isinstance(arango, dict) else {}
        return {
            "host": base.get("host") or host or _cfg("ARANGODB_HOST", "127.0.0.1"),
            "port": int(
                base.get("port") or port or _cfg("ARANGODB_PORT", 8529)
            ),
            "protocol": base.get("protocol")
            or protocol
            or _cfg("ARANGODB_PROTOCOL", "http"),
            "username": base.get("username")
            or user
            or _cfg("ARANGODB_USERNAME", "root"),
            "password": (
                base.get("password")
                if base.get("password") is not None
                else (
                    password
                    if password is not None
                    else _cfg("ARANGODB_PASSWORD", "")
                )
            ),
            "database": base.get("database")
            or database
            or _cfg("ARANGODB_DATABASE", f"db_{self.tenant_id}"),
        }

    def _resolve_files(self, source: Optional[Any]) -> List[Path]:
        """Expand ``source`` / ``self.path`` into a de-duplicated file list."""
        src = source if source is not None else self.path
        if src is None:
            raise ValueError(
                "No source provided and self.path is not set. Pass a source to "
                "load() or set it during initialization."
            )
        items = list(src) if isinstance(src, list) else [src]
        files: List[Path] = []
        for item in items:
            p = Path(item)
            if p.is_dir():
                for ext in self.extensions:
                    globber = p.rglob if self._recursive else p.glob
                    files.extend(sorted(globber(f"*{ext}")))
            elif p.is_file():
                files.append(p)
            else:
                self.logger.warning("Path %s is not a valid file or directory.", p)
        seen: set[Path] = set()
        ordered: List[Path] = []
        for f in files:
            if f not in seen:
                seen.add(f)
                ordered.append(f)
        return ordered

    def _node_to_document(self, node: UniversalNode) -> Document:
        """Convert a :class:`UniversalNode` into a canonical :class:`Document`."""
        domain_tags = node.domain_tags or {}
        metadata = self.create_metadata(
            path=node.source_uri
            or f"graphindex://{self.tenant_id}/{node.node_id}",
            doctype='graphindex_node',
            source_type=self._source_type,
            title=node.title,
            node_id=node.node_id,
            kind=node.kind.value,
            parent_id=node.parent_id,
            provenance=node.provenance.value,
            content_ref=node.content_ref,
            community_id=domain_tags.get("community_id"),
        )
        content = node.summary or node.title or ""
        return Document(page_content=content, metadata=metadata)
