---
id: FW-001
query_id: Q201
type: wiki_query
intent: "Orientation: ontology graph store backend registry"
executed_at: 2026-11-06T13:29:04Z
duration_ms: 3000
parent_id: null
depth: 0
---

# FW-001 — The ontology graph store already has a backend-neutral contract and an explicit registry (FEAT-540 M8); ArangoDB is one lazily-imported implementation

## Summary

`ontology/contracts.py` declares two ABCs — `GraphDocumentStore` (collection/document/edge CRUD) and `OntologyTraversalStore` (typed traversals + dialect-bound dynamic queries) — plus a `DynamicQuery(dialect=..., text=...)` model and an in-process registry: `register_ontology_backend(name, factory)` / `create_ontology_graph_store(backend, **options)`. The only built-in name is `"arangodb"`, resolved by a lazy import of `ArangoOntologyGraphStore` from `graph_store.py`. A contract test (`test_contracts.py`, tagged FEAT-540 M8) registers a fake backend and asserts the factory stays backend-neutral. A PostgreSQL ontology store therefore plugs in by `register_ontology_backend("postgres", ...)`, not by a new parallel protocol.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py`
  lines: 182-206
  symbol: `create_ontology_graph_store`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py#create_ontology_graph_store
  score: 1.00 (query "ontology graph store ArangoDB")
  excerpt: |
    def create_ontology_graph_store(backend: str, **options: Any) -> GraphDocumentStore:
        factory = _ONTOLOGY_BACKENDS.get(backend)
        if factory is not None:
            return factory(**options)
        if backend == "arangodb":
            from parrot.knowledge.ontology.graph_store import ArangoOntologyGraphStore
            return ArangoOntologyGraphStore(**options)
        raise ValueError(f"Unknown ontology graph backend {backend!r} — expected one of {known}")

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py`
  lines: 172-172
  symbol: `register_ontology_backend`
  excerpt: |
    def register_ontology_backend(name: str, factory: Callable[..., GraphDocumentStore]) -> None:

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py`
  lines: 26-26
  symbol: `GraphDocumentStore`
  excerpt: |
    class GraphDocumentStore(ABC):

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py`
  lines: 106-106
  symbol: `OntologyTraversalStore`
  excerpt: |
    class OntologyTraversalStore(ABC):

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py`
  lines: 17-17
  symbol: `DynamicQuery`
  excerpt: |
    class DynamicQuery(BaseModel):

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

- The symbol line numbers for `register_ontology_backend`, `GraphDocumentStore`, `OntologyTraversalStore` and `DynamicQuery` come from one confirming grep over `contracts.py` (not from the wiki page).
- The draft's `OntologyStore` Protocol (`resolve` / `expand` / `neighbors` / `canonical` / `export`) is a *different* surface from the existing `GraphDocumentStore` + `OntologyTraversalStore`; the proposal must say whether it replaces, wraps, or sits beside them. See FW-010 for the spec that created this seam.
- `DynamicQuery.collection_binds` shows the "neutral" contract still carries an Arango-shaped field.
- [cross-lane: type=read, intent=enumerate the abstract methods of GraphDocumentStore and OntologyTraversalStore (contracts.py:26-170) to map each to a Postgres relational/closure implementation]
