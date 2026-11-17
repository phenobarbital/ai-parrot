---
id: FC-002
query_id: Q002
type: read
intent: "Which operations does the ArangoDB ontology graph store implement, and how much raw AQL do they carry?"
executed_at: 2026-11-06T13:33:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-002 — ArangoOntologyGraphStore: one 1032-line class, one ArangoDB database per tenant, AQL built inline

## Summary

`ArangoOntologyGraphStore(GraphDocumentStore, OntologyTraversalStore)` is the only implementation of both ABCs (class spans lines 62-1032). It receives an `asyncdb.AsyncDB` client, switches database per call with `self._client.use(ctx.arango_db)` (**tenant isolation = one ArangoDB database per tenant**), and `initialize_tenant` provisions vertex collections per entity, edge collections per relation, a named graph, persistent indexes on `key_field`, and declared ArangoSearch views. Every operation funnels through `_execute_aql`; `is_reachable`, `find_by_field`, `search_by_name` build AQL text inline, and `execute_pattern` / `execute_query` run **caller-supplied AQL** (pattern templates from YAML, or LLM-generated dynamic queries) after only a dialect check. `dialect = "aql"`.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 62-100
  symbol: `ArangoOntologyGraphStore`
  excerpt: |
    class ArangoOntologyGraphStore(GraphDocumentStore, OntologyTraversalStore):
        dialect: ClassVar[str] = "aql"
        def __init__(self, arango_client: Any = None) -> None:
            self._client = arango_client
        async def _get_db(self, ctx: TenantContext) -> Any:
            # Use the tenant's database
            await self._client.use(ctx.arango_db)
            return self._client

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 102-116
  symbol: `ArangoOntologyGraphStore.initialize_tenant`
  excerpt: |
    """Create the ArangoDB database and all collections for a tenant.
    Idempotent — safe to call multiple times. Creates:
        1. Database (if not exists)
        2. Vertex collections for each entity
        3. Edge collections for each relation
        4. Named graph linking vertex/edge collections
        5. Indexes for key_field on each vertex collection
        6. Declared ArangoSearch views (``ctx.ontology.search_views``, FEAT-449 R15)

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 282-320
  symbol: `ArangoOntologyGraphStore._execute_aql`
  excerpt: |
    async def _execute_aql(self, ctx, aql: str, bind_vars=None, collection_binds=None) -> list[dict[str, Any]]:
        db = await self._get_db(ctx)
        ...
        result = await db.execute_query(aql, bind_vars=all_binds)

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 342-381
  symbol: `ArangoOntologyGraphStore.is_reachable`
  excerpt: |
    aql = f"FOR v IN 1..{depth} {keyword} @asker_id @@edge_collection " "FILTER v._id == @target_id " "RETURN v._id"
    rows = await self._execute_aql(
        ctx, aql,
        bind_vars={"asker_id": start_id, "target_id": target_id},
        collection_binds={"@edge_collection": edge_collection},
    )
    return bool(rows)

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 464-511
  symbol: `ArangoOntologyGraphStore.execute_pattern`
  excerpt: |
    templates = getattr(pattern, "query_templates", None) or {}
    aql = templates.get(self.dialect) or getattr(pattern, "query_template", None)
    if not aql:
        raise TraversalPatternUnavailable(f"Pattern has no {self.dialect!r} query template")
    return await self._execute_aql(ctx, aql, bind_vars=dict(params), collection_binds=dict(collection_binds or {}))
    ...
    if query.dialect != self.dialect:
        raise QueryDialectMismatch(f"Store dialect is {self.dialect!r}, query dialect is {query.dialect!r}")

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 24-59
  symbol: `UpsertResult`
  excerpt: |
    class UpsertResult(BaseModel):
        inserted: int = 0
        updated: int = 0
        unchanged: int = 0
    #: ArangoDB only accepts *literal* attribute names in an UPSERT example
    #: object (ERR 1501 for a bind parameter, and for a computed name), so the
    #: key field is interpolated into the AQL text.

## Notes

- Method outline (from `wikitoolkit symbols outline`): `initialize_tenant` L102-225, `_ensure_views` L227-261, `_ensure_index` L263-280, `_execute_aql` L282-320, `is_reachable` L342-381, `get_document_by_id` L383-394, `find_by_field` L396-427, `search_by_name` L429-462, `execute_pattern` L464-492, `execute_query` L494-511, `upsert_nodes` L513-614, `create_edges` L616-691, `get_all_nodes` L693-720, `soft_delete_nodes` L722-764, `ensure_collection` L775-801, `get_document` L803-825, `upsert_document` L827-853, `insert_document` L855-872, `remove_document` L874-900, `query_documents` L902-941, `get_all_edges` L943-967. Only L1-125, L282-381 and L464-512 were read in full.
- `UpsertResult` lives in the Arango module but is part of the neutral contract's return type (`contracts.py` imports it under `TYPE_CHECKING`) — it must move out before the Arango module can be deleted.
- `per-pattern "query_templates"` keyed by dialect is the existing multi-dialect hook: a non-AQL store raises `TraversalPatternUnavailable` unless every pattern ships a template in its dialect (see FC-004).
