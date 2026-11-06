---
id: F001
query_id: Q001
type: read
intent: "What is the existing ontology graph-store seam: protocol, backend registry and factory?"
executed_at: 2026-11-06T13:32:00Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-001, FW-001]
---

# F001 — A backend-neutral ontology store seam already exists (two ABCs + a name-keyed registry)

## Summary

`parrot/knowledge/ontology/contracts.py` (FEAT-540 M8, 206 lines) already defines the seam a replacement must plug into: `GraphDocumentStore` (14 abstract collection/document/edge CRUD methods, used by GraphIndex persistence) and `OntologyTraversalStore` (6 abstract methods + a `dialect` ClassVar, used by ontology callers), plus a registry `register_ontology_backend(name, factory)` / `create_ontology_graph_store(backend, **options)`. `"arangodb"` is the only built-in name (lazy import). The contract is **document/collection-shaped** (collections, `_key`-style documents, edge collections, `collection/key` ids) and exposes a raw-query escape hatch (`execute_query(DynamicQuery)` with `dialect`, `bind_vars`, `collection_binds`). It has nothing in common with the draft's `OntologyStore` Protocol (`resolve` / `expand` / `canonical` / `export`).

`ontology/contracts.py` declares two ABCs — `GraphDocumentStore` (collection/document/edge CRUD) and `OntologyTraversalStore` (typed traversals + dialect-bound dynamic queries) — plus a `DynamicQuery(dialect=..., text=...)` model and an in-process registry: `register_ontology_backend(name, factory)` / `create_ontology_graph_store(backend, **options)`. The only built-in name is `"arangodb"`, resolved by a lazy import of `ArangoOntologyGraphStore` from `graph_store.py`. A contract test (`test_contracts.py`, tagged FEAT-540 M8) registers a fake backend and asserts the factory stays backend-neutral. A PostgreSQL ontology store therefore plugs in by `register_ontology_backend("postgres", ...)`, not by a new parallel protocol.

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

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py`
  lines: 172-172
  symbol: `register_ontology_backend`
  excerpt: |
    def register_ontology_backend(name: str, factory: Callable[..., GraphDocumentStore]) -> None:

- path: `packages/ai-parrot/tests/knowledge/ontology/test_contracts.py`
  lines: 37-52
  symbol: `test_dynamic_query_defaults_and_custom_backend_registry`
  wiki_page_id: sym:packages/ai-parrot/tests/knowledge/ontology/test_contracts.py#test_dynamic_query_defaults_and_custom_backend_registry
  score: 1.00
  excerpt: |
    query = DynamicQuery(dialect="test", text="QUERY")
    assert query.bind_vars == {}
    assert query.collection_binds == {}
    register_ontology_backend("test-contracts", make_store)
    assert create_ontology_graph_store("test-contracts") is expected_store
    with pytest.raises(ValueError, match="Unknown ontology graph backend"):
        create_ontology_graph_store("missing-contracts")

## Notes

- The registry's return type is `GraphDocumentStore` only; the traversal ABC is a second, separate contract that the single Arango class happens to implement too.
- `TenantContext` and `TraversalPattern` are imported from `schema.py` (see F005) — the contract is coupled to the YAML ontology model.
- [cross-lane: type=wiki_query, intent=what did FEAT-540 M8 decide about the ontology store contract and which non-Arango backends it anticipated (docstrings mention HelixDB)]
- The symbol line numbers for `register_ontology_backend`, `GraphDocumentStore`, `OntologyTraversalStore` and `DynamicQuery` come from one confirming grep over `contracts.py` (not from the wiki page).
- The draft's `OntologyStore` Protocol (`resolve` / `expand` / `neighbors` / `canonical` / `export`) is a *different* surface from the existing `GraphDocumentStore` + `OntologyTraversalStore`; the proposal must say whether it replaces, wraps, or sits beside them. See F030 for the spec that created this seam.
- `DynamicQuery.collection_binds` shows the "neutral" contract still carries an Arango-shaped field.
- [cross-lane: type=read, intent=enumerate the abstract methods of GraphDocumentStore and OntologyTraversalStore (contracts.py:26-170) to map each to a Postgres relational/closure implementation]
