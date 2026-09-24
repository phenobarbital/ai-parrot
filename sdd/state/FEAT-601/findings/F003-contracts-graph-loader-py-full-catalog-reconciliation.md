---
id: F003
query_id: Q003
type: read
intent: ContractGraphLoader lifecycle; how publish deletes prior nodes/edges; where an origin=="manual" filter would go.
executed_at: 2026-09-24T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F003 — contracts/graph_loader.py full-catalog reconciliation

## Summary
`publish(card)` does not delete per contract. It hands off to `publish_all()`, which:
1. upserts every vertex in `SEED_ORDER`;
2. soft-deletes contract and obligation vertices that are no longer in the snapshot;
3. removes every edge in `FEATURE_EDGE_COLLECTIONS` whose endpoints aren't in `desired_edges()` or whose properties changed, then recreates the wanted edges;
4. reads everything back (`_verify`) before setting `published=True`.

No step looks at `origin`, so edges a technician added by hand in an owned collection would be removed on the next publish. `retract(contract_id)` is the only per-contract removal: it calls `soft_delete_nodes` and then `edges_incident`/`remove_edge_by_triple` for each owned edge collection.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py`
  lines: 50-68
  symbol: `CONTRACTS_DOMAIN` / `FEATURE_VERTEX_COLLECTIONS` / `FEATURE_EDGE_COLLECTIONS`
  excerpt: |
    CONTRACTS_DOMAIN = "contracts"
    FEATURE_VERTEX_COLLECTIONS: tuple[str, ...] = ("contract", "obligation")
    FEATURE_EDGE_COLLECTIONS: tuple[str, ...] = ("party_to","signed_by",...,"managed_by",)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py`
  lines: 106-154
  symbol: `EdgeSpec`
  excerpt: |
    collection; source_collection; source_key; target_collection; target_key
    properties: dict[str, Any]
    def document(self): {"_from","_to","source_id","target_id","kind": self.collection, **self.properties}
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py`
  lines: 157-179
  symbol: `GraphPublicationReport`
  excerpt: |
    published: bool = False; nodes_upserted; edges_created; edges_removed
    deactivated: dict[str, list[str]]; retracted; errors; missing_nodes; missing_edges
    def complete(self): return not (self.errors or self.missing_nodes or self.missing_edges)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py`
  lines: 197-213
  symbol: `ContractGraphLoader.__init__`
  excerpt: |
    def __init__(self, *, catalog: ContractCatalogStore, graph_store: Any, tenant_manager: Any = None,
                 datasource: Optional[ContractCardDataSource] = None,
                 ontology_dir=None, domain: str = CONTRACTS_DOMAIN) -> None:
        self.datasource = datasource or ContractCardDataSource("contractcard", {"catalog": catalog})
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py`
  lines: 227-249
  symbol: `ContractGraphLoader.context` / `startup_check`
  excerpt: |
    ctx = self._tenant_manager.resolve(self.catalog.tenant_id, domain=self.domain)
    missing = {"Contract", "Obligation", "Party"} - set(ctx.ontology.entities)
    if missing: raise ContractsDomainNotLoaded(...)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py`
  lines: 254-408
  symbol: `ContractGraphLoader.desired_edges`
  excerpt: |
    @staticmethod
    def desired_edges(snapshot: dict[str, list[dict[str, Any]]]) -> list[EdgeSpec]:
        for contract_id, record in sorted(contracts.items()):
            if not record.get("active", True): continue
        edges.sort(key=lambda edge: (edge.collection, edge.source_id, edge.target_id))
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py`
  lines: 471-488
  symbol: `ContractGraphLoader.publish_all` (soft-delete step)
  excerpt: |
    for entity in ("Contract", "Obligation"):
        existing = await self.graph_store.get_all_nodes(ctx, collection)
        obsolete = sorted(... if (node.get(key_field) or node.get("_key")) not in intended)
        if obsolete:
            await self.graph_store.soft_delete_nodes(ctx, collection, obsolete)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py`
  lines: 502-548
  symbol: `ContractGraphLoader._reconcile_edges`
  excerpt: |
    for collection in FEATURE_EDGE_COLLECTIONS:
        existing = await self.graph_store.get_all_edges(ctx, collection)
        for edge in existing:
            if wanted_edge is None:
                await self.graph_store.remove_edge_by_triple(ctx, collection, source, target, kind)
    created = await self.graph_store.create_edges(ctx, collection, [e.document() for e in wanted])
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py`
  lines: 550-592
  symbol: `ContractGraphLoader._verify`
  excerpt: |
    nodes = await self.graph_store.get_all_nodes(ctx, collection)
    report.missing_nodes.extend(f"{collection}/{key}" for key in sorted(intended - present))
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py`
  lines: 594-609
  symbol: `ContractGraphLoader.publish`
  excerpt: |
    v1 delegates to :meth:`publish_all`: the generic diff has no per-card filter and
    soft-deletes everything absent from the extraction it is given
    return await self.publish_all()
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py`
  lines: 611-675
  symbol: `ContractGraphLoader.retract`
  excerpt: |
    await self.graph_store.soft_delete_nodes(ctx, "contract", [contract_id])
    for collection in FEATURE_EDGE_COLLECTIONS:
        for node_id in node_ids:
            incident = await self.graph_store.edges_incident(ctx, collection, node_id)
            ... remove_edge_by_triple(...)

## Notes
- The brainstorm says the manuals loader can extend an existing `origin=="manual"` filter. That filter does not exist. `origin` appears only in a docstring (L115). The manuals loader has to:
  - stamp `origin` in `desired_edges`;
  - skip `origin=="manual"` in the `obsolete` comprehension (L481-485), in the `_reconcile_edges` removal branch (L522-536) and in `retract` (L656-664);
  - put technician tips in a separate collection outside `FEATURE_EDGE_COLLECTIONS`. That is the simpler option, because anything outside the owned collections is never touched.
- Graph-store methods used, i.e. the fake surface: `upsert_nodes`, `get_all_nodes`, `soft_delete_nodes`, `get_all_edges`, `remove_edge_by_triple`, `create_edges`, `edges_incident`.
- A "manuals" domain YAML plus a dedicated `TenantOntologyManager` are needed. The manager caches per tenant, not per domain (L190-193).
