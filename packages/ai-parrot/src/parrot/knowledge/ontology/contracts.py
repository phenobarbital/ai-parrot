"""Backend-neutral ontology graph-store contracts (FEAT-540 M8)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Callable, ClassVar

from pydantic import BaseModel, Field

from parrot.knowledge.ontology.schema import TenantContext, TraversalPattern

if TYPE_CHECKING:
    from .graph_store import UpsertResult


class DynamicQuery(BaseModel):
    """A dialect-bound query text with its bind parameters."""

    dialect: str
    text: str
    bind_vars: dict[str, Any] = Field(default_factory=dict)
    collection_binds: dict[str, str] = Field(default_factory=dict)


class GraphDocumentStore(ABC):
    """Collection, document, and edge CRUD needed by GraphIndex persistence."""

    @abstractmethod
    async def initialize_tenant(self, ctx: TenantContext) -> None:
        """Initialize the storage required for a tenant."""

    @abstractmethod
    async def ensure_collection(self, ctx: TenantContext, name: str, edge: bool = False) -> None:
        """Ensure a vertex or edge collection exists."""

    @abstractmethod
    async def upsert_nodes(
        self,
        ctx: TenantContext,
        collection: str,
        nodes: list[dict[str, Any]],
        key_field: str,
    ) -> UpsertResult:
        """Upsert nodes into a vertex collection."""

    @abstractmethod
    async def create_edges(self, ctx: TenantContext, edge_collection: str, edges: list[dict[str, Any]]) -> int:
        """Create edges in an edge collection."""

    @abstractmethod
    async def get_all_nodes(self, ctx: TenantContext, collection: str) -> list[dict[str, Any]]:
        """Return all active nodes in a collection."""

    @abstractmethod
    async def soft_delete_nodes(self, ctx: TenantContext, collection: str, keys: list[str]) -> None:
        """Soft-delete nodes identified by their keys."""

    @abstractmethod
    async def get_document(self, ctx: TenantContext, collection: str, key: str) -> dict[str, Any] | None:
        """Return a document by key when it exists."""

    @abstractmethod
    async def upsert_document(self, ctx: TenantContext, collection: str, doc: dict[str, Any]) -> None:
        """Upsert one document by key."""

    @abstractmethod
    async def insert_document(self, ctx: TenantContext, collection: str, doc: dict[str, Any]) -> None:
        """Insert one document."""

    @abstractmethod
    async def remove_document(self, ctx: TenantContext, collection: str, key: str) -> bool:
        """Remove one document by key."""

    @abstractmethod
    async def query_documents(
        self,
        ctx: TenantContext,
        collection: str,
        filters: dict[str, Any] | None = None,
        sort_desc: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Query documents with optional equality filters."""

    @abstractmethod
    async def get_all_edges(self, ctx: TenantContext, collection: str) -> list[dict[str, Any]]:
        """Return every edge in a collection."""

    @abstractmethod
    async def edges_incident(self, ctx: TenantContext, collection: str, node_id: str) -> list[dict[str, Any]]:
        """Return edges incident to a node."""

    @abstractmethod
    async def remove_edge_by_triple(
        self,
        ctx: TenantContext,
        collection: str,
        source_id: str,
        target_id: str,
        kind: str,
    ) -> bool:
        """Remove edges matching a source, target, and kind triple."""


class OntologyTraversalStore(ABC):
    """Backend-neutral traversal surface for ontology callers."""

    dialect: ClassVar[str]

    @abstractmethod
    async def is_reachable(
        self,
        ctx: TenantContext,
        start_id: str,
        target_id: str,
        *,
        edge_collection: str,
        max_depth: int,
        direction: str = "outbound",
    ) -> bool:
        """Return whether a typed traversal reaches a target."""

    @abstractmethod
    async def get_document_by_id(self, ctx: TenantContext, doc_id: str) -> dict[str, Any] | None:
        """Return a document addressed by its full identifier."""

    @abstractmethod
    async def find_by_field(
        self,
        ctx: TenantContext,
        collection: str,
        field: str,
        value: Any,
        *,
        filters: Mapping[str, Any] | None = None,
        limit: int = 2,
    ) -> list[dict[str, Any]]:
        """Find documents by exact field value."""

    @abstractmethod
    async def search_by_name(
        self,
        ctx: TenantContext,
        collection: str,
        needle: str,
        *,
        field: str = "name",
        filters: Mapping[str, Any] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Find documents by case-insensitive name containment."""

    @abstractmethod
    async def execute_pattern(
        self,
        ctx: TenantContext,
        pattern: TraversalPattern,
        params: Mapping[str, Any],
        collection_binds: Mapping[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Run a traversal pattern declared for this store dialect."""

    @abstractmethod
    async def execute_query(self, ctx: TenantContext, query: DynamicQuery) -> list[dict[str, Any]]:
        """Execute a dialect-bound dynamic query."""


_ONTOLOGY_BACKENDS: dict[str, Callable[..., GraphDocumentStore]] = {}


def register_ontology_backend(name: str, factory: Callable[..., GraphDocumentStore]) -> None:
    """Register or replace an ontology graph-store backend factory.

    Args:
        name: Backend name selected by callers.
        factory: Callable that constructs the selected graph document store.
    """
    _ONTOLOGY_BACKENDS[name] = factory


def create_ontology_graph_store(backend: str, **options: Any) -> GraphDocumentStore:
    """Create an ontology graph store from the registered backend name.

    The built-in ArangoDB store is imported only when requested so importing
    the contracts does not load optional database dependencies.

    Args:
        backend: Registered backend name, or ``"arangodb"``.
        **options: Backend constructor keyword arguments.

    Returns:
        The requested graph document store.

    Raises:
        ValueError: If ``backend`` is not registered.
    """
    factory = _ONTOLOGY_BACKENDS.get(backend)
    if factory is not None:
        return factory(**options)
    if backend == "arangodb":
        from parrot.knowledge.ontology.graph_store import OntologyGraphStore

        return OntologyGraphStore(**options)
    known = ", ".join(repr(name) for name in (*_ONTOLOGY_BACKENDS, "arangodb"))
    raise ValueError(f"Unknown ontology graph backend {backend!r} — expected one of {known}")
