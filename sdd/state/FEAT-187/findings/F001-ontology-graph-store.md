---
id: F001
query: Q001
type: read
target: packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py
---

# F001 — OntologyGraphStore Class Verification

**Status**: Confirmed with minor notes

`OntologyGraphStore` at `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`.
No base class (plain class, not ABC).

## Public Methods (all async)

| Method | Signature | Return |
|--------|-----------|--------|
| `initialize_tenant` | `(ctx: TenantContext) -> None` | Creates DB, vertex/edge collections, indexes, named graph |
| `upsert_nodes` | `(ctx, collection, nodes: list[dict], key_field: str) -> UpsertResult` | Sets `_active: true` on all upserted docs |
| `create_edges` | `(ctx, edge_collection, edges: list[dict]) -> int` | Upserts on `(_from, _to)` composite |
| `get_all_nodes` | `(ctx, collection) -> list[dict]` | Filters by `_active != false` |
| `soft_delete_nodes` | `(ctx, collection, keys: list[str]) -> None` | Sets `_active: false` by `_key` values |
| `execute_traversal` | `(ctx, aql, bind_vars?, collection_binds?) -> list[dict]` | AQL execution |

`UpsertResult(BaseModel)`: `inserted: int = 0`, `updated: int = 0`, `unchanged: int = 0`

## Notes
- `soft_delete_nodes` uses `_key` values, not `key_field`
- `upsert_nodes` has per-node fallback on batch failure
- Named graph pattern: `f"{ctx.tenant_id}_ontology_graph"`
