---
id: F010
query_id: Q010
type: read
intent: OntologyGraphStore API — execute_traversal, upsert_nodes, create_edges edge shape, soft_delete_nodes fields, remove_edge_by_triple, edges_incident, ensure_collection, initialize_tenant
executed_at: 2026-09-24T23:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F010 — OntologyGraphStore write/read seams and their edge-identity quirks

## Summary
`upsert_nodes` matches nodes on the literal `key_field`, copies that value into `_key`, and sets `_active:true`. `soft_delete_nodes` only sets `_active:false` for a list of `_key`s; it cannot filter by other fields. `query_documents` can do equality filters, e.g. `{"origin": "manual"}`. `create_edges` stores arbitrary edge documents, but it upserts on `{_from,_to}` with `UPDATE {}`. Edge properties are never updated, and a second edge between the same pair of nodes is dropped. The commit helpers `edges_incident` and `remove_edge_by_triple` match on `source_id`/`target_id`/`kind`, not `_from`/`_to`. Edges only work with them if the writer stores those extra fields. There is no edge soft-delete.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 91-214
  symbol: `OntologyGraphStore.initialize_tenant`
  excerpt: |
    async def initialize_tenant(self, ctx: TenantContext) -> None:
        """Idempotent — creates DB, vertex collections per entity, edge
        collections per relation, named graph, key_field indexes, search views"""
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 271-309
  symbol: `OntologyGraphStore.execute_traversal`
  excerpt: |
    async def execute_traversal(self, ctx, aql: str,
        bind_vars: dict[str, Any] | None = None,
        collection_binds: dict[str, str] | None = None) -> list[dict[str, Any]]:
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 311-409
  symbol: `OntologyGraphStore.upsert_nodes`
  excerpt: |
    async def upsert_nodes(self, ctx, collection: str, nodes: list[dict], key_field: str) -> UpsertResult:
    ...
        UPSERT {{ {key_attr}: doc.{key_attr} }}
        INSERT MERGE(doc, {{ _key: doc.{key_attr}, _active: true }})
        UPDATE MERGE(doc, {{ _active: true }})
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 411-486
  symbol: `OntologyGraphStore.create_edges`
  excerpt: |
    async def create_edges(self, ctx, edge_collection: str, edges: list[dict]) -> int:
    FOR edge IN @edges
        UPSERT { _from: edge._from, _to: edge._to }
        INSERT edge
        UPDATE {}
        IN @@collection
        RETURN NEW ? 1 : 0
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 517-559
  symbol: `OntologyGraphStore.soft_delete_nodes`
  excerpt: |
    async def soft_delete_nodes(self, ctx, collection: str, keys: list[str]) -> None:
    FOR key IN @keys
        UPDATE { _key: key } WITH { _active: false }
        IN @@collection
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 570-596
  symbol: `OntologyGraphStore.ensure_collection`
  excerpt: |
    async def ensure_collection(self, ctx, name: str, edge: bool = False) -> None:
        if not await db.collection_exists(name):
            await db.create_collection(name, edge=True)  # or plain
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 697-736
  symbol: `OntologyGraphStore.query_documents`
  excerpt: |
    async def query_documents(self, ctx, collection: str,
        filters: Optional[dict[str, Any]] = None,
        sort_desc: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
        clauses.append(f"FILTER doc.{field} == @f{i}")
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 764-789
  symbol: `OntologyGraphStore.edges_incident`
  excerpt: |
    async def edges_incident(self, ctx, collection: str, node_id: str) -> list[dict]:
        FILTER e.source_id == @node_id OR e.target_id == @node_id
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 791-827
  symbol: `OntologyGraphStore.remove_edge_by_triple`
  excerpt: |
    async def remove_edge_by_triple(self, ctx, collection, source_id, target_id, kind) -> bool:
        FILTER e.source_id == @src AND e.target_id == @tgt
           AND e.kind == @kind
        REMOVE e IN @@collection
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py`
  lines: 12-17
  symbol: `module docstring (edge reconciliation rule)`
  excerpt: |
    ``create_edges`` inserts or skips by endpoints and never updates
    properties or removes obsolete edges ... Every written edge carries
    ``_from``/``_to`` **plus** ``source_id``/``target_id``/``kind`` so the
    generic removal helpers can address it.
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py`
  lines: 502-548
  symbol: `ContractGraphLoader._reconcile_edges`
  excerpt: |
    stale_properties = any(edge.get(name) != value for name, value in wanted_edge.properties.items())
    if stale_properties or not edge.get("source_id"):
        await self.graph_store.remove_edge_by_triple(ctx, collection, source, target, edge.get("kind") or collection)
    ...
    created = await self.graph_store.create_edges(ctx, collection, [edge.document() for edge in wanted])

## Notes
- `create_edges` returns `NEW ? 1 : 0`. `NEW` is set on both insert and the no-op update, so the returned "created" count is inflated.
- The (_from,_to) identity rule breaks some FEAT-601 edges. Examples: a Step that `requires_part` the same Part in two different contexts, or `illustrated_by` the same Media with two roles. A composite target like `Step→Media#role` or a distinct `_key` would require a new write path. Otherwise, collapse such edges into a single edge with a list property.
- The node `_key` must pass `_literal_attribute` (L42-50). Composite step ids like `manual:proc:step` must stay within Arango's allowed `_key` characters.

