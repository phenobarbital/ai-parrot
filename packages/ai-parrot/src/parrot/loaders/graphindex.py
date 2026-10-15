"""GraphIndexLoader — framework loader over the GraphIndex builder.

This module is the framework-facing adapter for GraphIndex. The graph tree
receives its persistence target through the backend registry while this loader
continues to expose framework ``Document`` objects to callers.
"""

from __future__ import annotations

import inspect
import tempfile
from pathlib import Path
from typing import Any, List, Optional, Union

from parrot.knowledge.graphindex.backends import create_graph_persistence
from parrot.knowledge.graphindex.builder import GraphIndexBuilder
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder
from parrot.knowledge.graphindex.meta_ontology import build_graphindex_ontology
from parrot.knowledge.graphindex.models import GraphDocument
from parrot.knowledge.graphindex.schema import BuildResult, SourceConfig, UniversalEdge, UniversalNode
from parrot.knowledge.ontology.contracts import create_ontology_graph_store
from parrot.knowledge.ontology.schema import TenantContext
from parrot.knowledge.wiki.project import resolve_setting
from parrot.loaders.abstract import AbstractLoader
from parrot.stores.models import Document


def to_graph_document(doc: Document) -> GraphDocument:
    """Convert a framework document to a GraphIndex document."""
    return GraphDocument(page_content=doc.page_content, metadata=dict(doc.metadata))


def from_graph_document(doc: GraphDocument) -> Document:
    """Convert a GraphIndex document to a framework document."""
    return Document(page_content=doc.page_content, metadata=dict(doc.metadata))


class _CapturingPersistence:
    """Decorator that records assembled nodes and edges before delegating."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.nodes: list[UniversalNode] = []
        self.edges: list[UniversalEdge] = []

    async def persist_graph(self, ctx: Any, nodes: list[Any], edges: list[Any]) -> dict[str, Any]:
        """Persist a graph while retaining its native artifacts."""
        self.nodes = list(nodes)
        self.edges = list(edges)
        return await self._inner.persist_graph(ctx, nodes, edges)

    async def replace_document_slice(
        self, ctx: Any, document_uri: str, nodes: list[Any], edges: list[Any]
    ) -> dict[str, Any]:
        """Replace one source slice while retaining its native artifacts."""
        self.nodes = list(nodes)
        self.edges = list(edges)
        return await self._inner.replace_document_slice(ctx, document_uri, nodes, edges)

    def __getattr__(self, name: str) -> Any:
        """Delegate non-callable attributes to the wrapped persistence."""
        if name.startswith("__") or name == "_inner":
            raise AttributeError(name)
        return getattr(self._inner, name)


def _make_forwarder(name: str) -> Any:
    async def _forward(self: Any, *args: Any, **kwargs: Any) -> Any:
        return await getattr(self._inner, name)(*args, **kwargs)

    _forward.__name__ = name
    return _forward


def capture_persistence(inner: Any) -> _CapturingPersistence:
    """Wrap ``inner`` so every public method it exposes is forwarded.

    Protocol ``isinstance`` checks (``IncrementalPersistence``,
    ``EmbeddingPersistence``, ...) look methods up on the type, so forwarders
    are generated on a per-inner subclass rather than via ``__getattr__``.
    """
    namespace: dict[str, Any] = {}
    for name in dir(inner):
        if name.startswith("_") or name in _CapturingPersistence.__dict__:
            continue
        if callable(getattr(type(inner), name, None)) and inspect.iscoroutinefunction(getattr(inner, name)):
            namespace[name] = _make_forwarder(name)
    cls = type("_CapturingPersistence", (_CapturingPersistence,), namespace)
    return cls(inner)


class GraphIndexLoader(AbstractLoader):
    """Build a GraphIndex graph from a list of files.

    Args:
        source: Path, directory, or list of paths to index.
        backend: Explicit persistence backend; incompatible legacy arguments raise.
        persist_enabled: Set to ``False`` to select the ``null`` backend.
    """

    extensions: List[str] = [".pdf", ".md", ".markdown", ".txt", ".text", ".html", ".htm", ".docx"]

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
        arango: Optional[dict[str, Any]] = None,
        arango_host: Optional[str] = None,
        arango_port: Optional[int] = None,
        arango_protocol: Optional[str] = None,
        arango_user: Optional[str] = None,
        arango_password: Optional[str] = None,
        arango_database: Optional[str] = None,
        storage_dir: Optional[Union[str, Path]] = None,
        sqlite_dir: Optional[Union[str, Path]] = None,
        backend: str | None = None,
        persist_enabled: bool | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(source, **kwargs)
        self.doctype = "graphindex_node"
        self.tenant_id = tenant_id
        self.detect_communities = detect_communities
        self._output_dir = Path(output_dir) if output_dir is not None else None
        self.pgvector_dsn = pgvector_dsn
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
        self.embedder = GraphIndexEmbedder(model_name=embedding_model, dimension=embedding_dim)
        self._arango_params = self._resolve_arango(
            arango, arango_host, arango_port, arango_protocol, arango_user, arango_password, arango_database
        )
        self._sqlite_dir = Path(sqlite_dir) if sqlite_dir is not None else None
        self._backend = self._resolve_backend(backend=backend, persist_enabled=persist_enabled)
        self.persist_enabled = self._backend != "null"
        self.arango_db = arango_database or (self._arango_params or {}).get("database") or f"db_{tenant_id}"
        self._ontology = build_graphindex_ontology()
        self.ctx = TenantContext(
            tenant_id=tenant_id,
            arango_db=self.arango_db,
            pgvector_schema=f"schema_{tenant_id}",
            ontology=self._ontology,
        )
        self.build_result: Optional[BuildResult] = None
        self.nodes: List[UniversalNode] = []
        self.edges: List[UniversalEdge] = []
        self.graph_store: Any = None
        self._arango_db: Any = None
        self.builder: Optional[GraphIndexBuilder] = None

    async def load(self, source: Optional[Any] = None, split_documents: bool = False, **kwargs: Any) -> List[Document]:
        """Run the pipeline and return one document per graph node."""
        del split_documents, kwargs
        await self.build_graph(source)
        return [self._node_to_document(node) for node in self.nodes]

    async def build_graph(self, source: Optional[Any] = None) -> BuildResult:
        """Run the GraphIndex pipeline and expose its resulting artifacts."""
        files = self._resolve_files(source)
        try:
            inner = await self._make_persistence()
        except BaseException:
            await self._close_arango_db()
            raise
        try:
            return await self._build_with(inner, files)
        finally:
            try:
                await inner.close()
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.warning("persistence close failed: %s", exc)
            await self._close_arango_db()

    async def _close_arango_db(self) -> None:
        """Close the ArangoDB client opened by ``_make_persistence`` (the loader owns it)."""
        db, self._arango_db = self._arango_db, None
        if db is None:
            return
        try:
            result = db.close()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("ArangoDB client close failed: %s", exc)

    async def _build_with(self, inner: Any, files: Any) -> BuildResult:
        """Run the builder over ``inner`` wrapped with node/edge capture."""
        capture = capture_persistence(inner)
        output_dir = self._output_dir or Path(tempfile.mkdtemp(prefix="graphindex_"))
        self.builder = GraphIndexBuilder(
            persistence=capture,
            embedder=self.embedder,
            output_dir=output_dir,
            pageindex_toolkit=self._pageindex_toolkit,
            detect_communities_enabled=self.detect_communities,
        )
        sources = SourceConfig(tenant_id=self.tenant_id, loader_sources=[str(file) for file in files])
        result = await self.builder.build(sources, self.ctx)
        self.build_result = result
        self.nodes = capture.nodes
        self.edges = capture.edges
        return result

    async def _load(self, source: Union[str, Path], **kwargs: Any) -> List[Document]:
        """Build a graph for one source and return its node documents."""
        del kwargs
        await self.build_graph([source])
        return [self._node_to_document(node) for node in self.nodes]

    async def _make_persistence(self) -> Any:
        """Create the selected persistence backend through the registry."""
        options: dict[str, Any] = {}
        if self._backend == "sqlite":
            options["db_dir"] = self._sqlite_dir
        elif self._backend == "arangodb":
            from asyncdb import AsyncDB

            db = AsyncDB("arangodb", params=self._arango_params)
            try:
                await db.connection()
            except Exception as exc:  # pragma: no cover - requires a live server
                self.logger.error("ArangoDB connection failed: %s", exc)
                raise
            self._arango_db = db
            self.graph_store = create_ontology_graph_store("arangodb", arango_client=db)
            try:
                await self.graph_store.initialize_tenant(self.ctx)
            except Exception as exc:  # pragma: no cover - requires a live server
                self.logger.warning("initialize_tenant failed (collections may already exist): %s", exc)
            options.update(graph_store=self.graph_store, arango_params=self._arango_params, tenant_ctx=self.ctx)
        return await create_graph_persistence(self._backend, **options)

    def _resolve_backend(self, *, backend: str | None, persist_enabled: bool | None) -> str:
        """Resolve explicit and legacy persistence arguments without silent conflicts."""
        has_sqlite = self._sqlite_dir is not None
        has_arango = self._arango_params is not None
        if has_sqlite and has_arango:
            raise ValueError("sqlite_dir and ArangoDB parameters cannot be combined")
        if persist_enabled is False:
            if backend not in (None, "null") or has_sqlite or has_arango:
                raise ValueError("persist_enabled=False conflicts with an explicit persistence backend")
            return "null"
        if backend is not None:
            if has_sqlite and backend != "sqlite":
                raise ValueError("sqlite_dir conflicts with the explicit backend")
            if has_arango and backend != "arangodb":
                raise ValueError("ArangoDB parameters conflict with the explicit backend")
            return backend
        if has_sqlite:
            return "sqlite"
        if has_arango:
            return "arangodb"
        return "null"

    def _resolve_arango(
        self,
        arango: Optional[dict[str, Any]],
        host: Optional[str],
        port: Optional[int],
        protocol: Optional[str],
        user: Optional[str],
        password: Optional[str],
        database: Optional[str],
    ) -> Optional[dict[str, Any]]:
        """Resolve explicitly requested Arango parameters through ``resolve_setting``.

        Raises:
            ValueError: When no host is configured (no implicit loopback default).
        """
        explicit = arango is not None or any(value is not None for value in (host, user, password, database))
        if not explicit:
            return None
        base = dict(arango) if isinstance(arango, dict) else {}
        resolved_host = resolve_setting("ARANGODB_HOST", explicit=base.get("host") or host)
        if not resolved_host:
            # Same rule as wiki ``resolve_arango_params``: never silently select loopback.
            raise ValueError(
                "Missing required ArangoDB setting: ARANGODB_HOST (pass arango_host=... / arango={'host': ...} "
                "or set ARANGODB_HOST; an explicit 127.0.0.1 is accepted)"
            )
        return {
            "host": resolved_host,
            "port": int(resolve_setting("ARANGODB_PORT", default=8529, explicit=base.get("port") or port)),
            "protocol": resolve_setting("ARANGODB_PROTOCOL", default="http", explicit=base.get("protocol") or protocol),
            "username": resolve_setting("ARANGODB_USERNAME", default="root", explicit=base.get("username") or user),
            "password": resolve_setting(
                "ARANGODB_PASSWORD",
                default="",
                explicit=base.get("password") if base.get("password") is not None else password,
            ),
            "database": resolve_setting(
                "ARANGODB_DATABASE", default=f"db_{self.tenant_id}", explicit=base.get("database") or database
            ),
        }

    def _resolve_files(self, source: Optional[Any]) -> List[Path]:
        """Expand a source into an ordered, de-duplicated file list."""
        src = source if source is not None else self.path
        if src is None:
            raise ValueError(
                "No source provided and self.path is not set. Pass a source to load() or set it during initialization."
            )
        items = list(src) if isinstance(src, list) else [src]
        files: List[Path] = []
        for item in items:
            path = Path(item)
            if path.is_dir():
                for extension in self.extensions:
                    globber = path.rglob if self._recursive else path.glob
                    files.extend(sorted(globber(f"*{extension}")))
            elif path.is_file():
                files.append(path)
            else:
                self.logger.warning("Path %s is not a valid file or directory.", path)
        seen: set[Path] = set()
        ordered: List[Path] = []
        for file in files:
            if file not in seen:
                seen.add(file)
                ordered.append(file)
        return ordered

    def _node_to_document(self, node: UniversalNode) -> Document:
        """Convert a graph node to its framework document representation."""
        domain_tags = node.domain_tags or {}
        metadata = self.create_metadata(
            path=node.source_uri or f"graphindex://{self.tenant_id}/{node.node_id}",
            doctype="graphindex_node",
            source_type=self._source_type,
            title=node.title,
            node_id=node.node_id,
            kind=node.kind.value,
            parent_id=node.parent_id,
            provenance=node.provenance.value,
            content_ref=node.content_ref,
            community_id=domain_tags.get("community_id"),
        )
        return Document(page_content=node.summary or node.title or "", metadata=metadata)
