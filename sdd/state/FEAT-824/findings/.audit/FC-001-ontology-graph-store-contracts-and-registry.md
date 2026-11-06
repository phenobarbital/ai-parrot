---
id: FC-001
query_id: Q001
type: read
intent: "What is the existing ontology graph-store seam: protocol, backend registry and factory?"
executed_at: 2026-11-06T13:32:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-001 — A backend-neutral ontology store seam already exists (two ABCs + a name-keyed registry)

## Summary

`parrot/knowledge/ontology/contracts.py` (FEAT-540 M8, 206 lines) already defines the seam a replacement must plug into: `GraphDocumentStore` (14 abstract collection/document/edge CRUD methods, used by GraphIndex persistence) and `OntologyTraversalStore` (6 abstract methods + a `dialect` ClassVar, used by ontology callers), plus a registry `register_ontology_backend(name, factory)` / `create_ontology_graph_store(backend, **options)`. `"arangodb"` is the only built-in name (lazy import). The contract is **document/collection-shaped** (collections, `_key`-style documents, edge collections, `collection/key` ids) and exposes a raw-query escape hatch (`execute_query(DynamicQuery)` with `dialect`, `bind_vars`, `collection_binds`). It has nothing in common with the draft's `OntologyStore` Protocol (`resolve` / `expand` / `canonical` / `export`).

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py`
  lines: 17-23
  symbol: `DynamicQuery`
  excerpt: |
    class DynamicQuery(BaseModel):
        """A dialect-bound query text with its bind parameters."""
        dialect: str
        text: str
        bind_vars: dict[str, Any] = Field(default_factory=dict)
        collection_binds: dict[str, str] = Field(default_factory=dict)

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py`
  lines: 26-103
  symbol: `GraphDocumentStore`
  excerpt: |
    class GraphDocumentStore(ABC):
        """Collection, document, and edge CRUD needed by GraphIndex persistence."""
        async def initialize_tenant(self, ctx: TenantContext) -> None:
        async def ensure_collection(self, ctx: TenantContext, name: str, edge: bool = False) -> None:
        async def upsert_nodes(self, ctx, collection: str, nodes: list[dict[str, Any]], key_field: str) -> UpsertResult:
        async def create_edges(self, ctx: TenantContext, edge_collection: str, edges: list[dict[str, Any]]) -> int:
        # + get_all_nodes, soft_delete_nodes, get_document, upsert_document, insert_document,
        #   remove_document, query_documents, get_all_edges, edges_incident, remove_edge_by_triple

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py`
  lines: 106-166
  symbol: `OntologyTraversalStore`
  excerpt: |
    class OntologyTraversalStore(ABC):
        """Backend-neutral traversal surface for ontology callers."""
        dialect: ClassVar[str]
        async def is_reachable(self, ctx, start_id, target_id, *, edge_collection: str, max_depth: int, direction: str = "outbound") -> bool:
        async def get_document_by_id(self, ctx: TenantContext, doc_id: str) -> dict[str, Any] | None:
        async def find_by_field(self, ctx, collection, field, value, *, filters=None, limit: int = 2) -> list[dict[str, Any]]:
        async def search_by_name(self, ctx, collection, needle, *, field="name", filters=None, limit: int = 10) -> list[dict[str, Any]]:
        async def execute_pattern(self, ctx, pattern: TraversalPattern, params, collection_binds=None) -> list[dict[str, Any]]:
        async def execute_query(self, ctx: TenantContext, query: DynamicQuery) -> list[dict[str, Any]]:

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py`
  lines: 169-206
  symbol: `create_ontology_graph_store`
  excerpt: |
    _ONTOLOGY_BACKENDS: dict[str, Callable[..., GraphDocumentStore]] = {}
    def register_ontology_backend(name: str, factory: Callable[..., GraphDocumentStore]) -> None:
        _ONTOLOGY_BACKENDS[name] = factory
    def create_ontology_graph_store(backend: str, **options: Any) -> GraphDocumentStore:
        factory = _ONTOLOGY_BACKENDS.get(backend)
        if factory is not None:
            return factory(**options)
        if backend == "arangodb":
            from parrot.knowledge.ontology.graph_store import ArangoOntologyGraphStore
            return ArangoOntologyGraphStore(**options)

## Notes

- The registry's return type is `GraphDocumentStore` only; the traversal ABC is a second, separate contract that the single Arango class happens to implement too.
- `TenantContext` and `TraversalPattern` are imported from `schema.py` (see FC-005) — the contract is coupled to the YAML ontology model.
- [cross-lane: type=wiki_query, intent=what did FEAT-540 M8 decide about the ontology store contract and which non-Arango backends it anticipated (docstrings mention HelixDB)]
