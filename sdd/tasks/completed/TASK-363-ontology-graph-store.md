# TASK-363: Ontology Graph Store — ArangoDB Operations

**Feature**: Ontological Graph RAG
**Spec**: `sdd/specs/ontological-graph-rag.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (3-5h)
**Depends-on**: TASK-360
**Assigned-to**: —

---

## Context

> ArangoDB wrapper for ontology graph operations — tenant initialization, AQL traversals,
> node upsert, edge creation. Uses `python-arango-async`.
> Implements spec Module 8.

---

## Scope

### Create `parrot/knowledge/ontology/graph_store.py`

`OntologyGraphStore`:
- `__init__(self, arango_client)` — receive ArangoDB client from connection pool.
- `async initialize_tenant(self, ctx: TenantContext)` — create DB, vertex/edge collections, named graph, indexes. Idempotent.
- `async execute_traversal(self, ctx: TenantContext, aql: str, bind_vars: dict, collection_binds: dict | None = None) -> list[dict]` — execute AQL with bind variables. Resolve `@@collection` binds.
- `async upsert_nodes(self, ctx: TenantContext, collection: str, nodes: list[dict], key_field: str) -> UpsertResult` — batch upsert using ArangoDB native UPSERT.
- `async create_edges(self, ctx: TenantContext, edge_collection: str, edges: list[dict]) -> int` — create edges, deduplicate on `_from + _to`.
- `async get_all_nodes(self, ctx: TenantContext, collection: str) -> list[dict]` — retrieve all nodes (for diff during refresh).
- `async soft_delete_nodes(self, ctx: TenantContext, collection: str, keys: list[str])` — mark nodes as `_active: false`.

`UpsertResult(BaseModel)`:
- `inserted: int`
- `updated: int`
- `unchanged: int`

---

## Acceptance Criteria

- [ ] `initialize_tenant()` creates DB, collections, graph, indexes. Idempotent (no error on re-run).
- [ ] `execute_traversal()` resolves `@@collection` bind variables.
- [ ] `upsert_nodes()` correctly inserts new and updates changed nodes.
- [ ] `create_edges()` deduplicates on `_from + _to`.
- [ ] `soft_delete_nodes()` marks nodes inactive (not hard delete).
- [ ] All methods are async, using `python-arango-async`.
- [ ] Unit tests with mocked ArangoDB client.

---

## Files to Create / Modify

| File | Action |
|---|---|
| `parrot/knowledge/ontology/graph_store.py` | **Create** |
| `tests/knowledge/test_ontology_graph_store.py` | **Create** |
