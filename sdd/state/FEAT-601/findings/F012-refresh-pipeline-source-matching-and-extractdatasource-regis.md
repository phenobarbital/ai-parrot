---
id: F012
query_id: Q012
type: read
intent: OntologyRefreshPipeline.run; how ExtractDataSource is matched to EntityDef.source; ExtractDataSource base; how contractcard is registered
executed_at: 2026-09-24T23:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F012 — Refresh pipeline source matching and ExtractDataSource registration

## Summary
`OntologyRefreshPipeline.run(tenant_id, domain)` resolves the tenant context, then for every entity with a `source` calls `datasource_factory.get(entity_def.source, source_configs.get(source, {}))`. Each entity gets a fresh source instance, and extraction is `extract(fields=entity property names)`. It diffs against `get_all_nodes`, then upserts, soft-deletes anything missing, and re-runs `RelationDiscovery.discover` only for outgoing relations of changed nodes. `ExtractDataSource` (ABC, `__init__(name, config)`, abstract `extract(fields, filters)` and `list_fields`) lives in `parrot_loaders.extractors.base`. `DataSourceFactory.register_api_source(name, cls)` writes to a class-level dict. `contractcard` registers itself at import time via `datasource.register()`, and `ContractCardDataSource.infer_entity(fields)` figures out which entity a call is for from the requested fields.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py`
  lines: 76-92
  symbol: `OntologyRefreshPipeline.__init__`
  excerpt: |
    def __init__(self, tenant_manager, graph_store, discovery, datasource_factory: Any,
                 cache, vector_store=None, source_configs: dict[str, dict[str, Any]] | None = None)
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py`
  lines: 94-143
  symbol: `OntologyRefreshPipeline.run`
  excerpt: |
    ctx = self.tenant_manager.resolve(tenant_id, domain=domain)
    for entity_name, entity_def in ctx.ontology.entities.items():
        if not entity_def.source:
            continue
        await self._refresh_entity(ctx, entity_name, entity_def, report)
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py`
  lines: 158-176
  symbol: `OntologyRefreshPipeline._refresh_entity (extract)`
  excerpt: |
    source_config = self.source_configs.get(entity_def.source, {})
    source = self.datasource_factory.get(entity_def.source, source_config)
    property_names = list(entity_def.get_property_names())
    extraction = await source.extract(fields=property_names)
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/refresh.py`
  lines: 187-222
  symbol: `OntologyRefreshPipeline._refresh_entity (apply/rediscover)`
  excerpt: |
    if diff.to_remove:
        await self.graph_store.soft_delete_nodes(ctx, entity_def.collection, keys_to_remove)
    for rel_name, rel_def in ctx.ontology.relations.items():
        if rel_def.from_entity == entity_name:
            discovery_result = await self.discovery.discover(ctx, rel_def, changed_nodes, target_data)
            await self.graph_store.create_edges(ctx, rel_def.edge_collection, discovery_result.confirmed)
- path: `packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py`
  lines: 50-90
  symbol: `ExtractDataSource`
  excerpt: |
    class ExtractDataSource(ABC):
        def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        @abstractmethod
        async def extract(self, fields: list[str] | None = None,
                          filters: dict[str, Any] | None = None) -> ExtractionResult:
- path: `packages/ai-parrot-loaders/src/parrot_loaders/extractors/base.py`
  lines: 18-48
  symbol: `ExtractedRecord, ExtractionResult`
  excerpt: |
    class ExtractedRecord(BaseModel):
        data: dict[str, Any]
        metadata: dict[str, Any] = Field(default_factory=dict)
    class ExtractionResult(BaseModel):
        records: list[ExtractedRecord]; total: int; errors: list[str]; source_name: str; extracted_at: datetime
- path: `packages/ai-parrot-loaders/src/parrot_loaders/extractors/factory.py`
  lines: 35-80
  symbol: `DataSourceFactory.register_api_source / get`
  excerpt: |
    @classmethod
    def register_api_source(cls, name: str, source_cls: type[ExtractDataSource]) -> None:
        cls._api_registry[name] = source_cls
    def get(self, source_name, source_config=None) -> ExtractDataSource:
        source_type = cfg.get("type", source_name)
        if source_type in self._api_registry:
            return cls(name=source_name, config=cfg)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/datasource.py`
  lines: 130-158
  symbol: `ContractCardDataSource.__init__`
  excerpt: |
    class ContractCardDataSource(ExtractDataSource):
        def __init__(self, name: str = SOURCE_NAME, config: Optional[dict[str, Any]] = None) -> None:
            super().__init__(name=name, config=config or {})
            catalog = self.config.get("catalog")
            if not isinstance(catalog, ContractCatalogStore): raise ValueError(...)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/datasource.py`
  lines: 160-191
  symbol: `ContractCardDataSource.infer_entity`
  excerpt: |
    if not fields: return "Contract"
    for marker, entity in ENTITY_ROUTING_ORDER:
        if marker in requested:
            unknown = requested - ENTITY_FIELDS[entity]
            if unknown: raise UnknownFieldRequest(...)
            return entity
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/datasource.py`
  lines: 447-458
  symbol: `register`
  excerpt: |
    def register() -> None:
        if not _LOADERS_AVAILABLE: return
        DataSourceFactory.register_api_source(SOURCE_NAME, ContractCardDataSource)
    register()
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/graph_loader.py`
  lines: 211
  symbol: `ContractGraphLoader.__init__ (datasource)`
  excerpt: |
    self.datasource = datasource or ContractCardDataSource("contractcard", {"catalog": catalog})

## Notes
- `run()` passes only `fields=`, never `filters=`, and never the entity name. A multi-entity source (Equipment/Manual/Procedure/Step/...) must work out the entity from the fields, like contracts `infer_entity`. The alternative is one source name per entity.
- `_refresh_entity` soft-deletes every node missing from an extraction (L193-198). Partial or per-manual extraction would retract everything else. Contracts avoids this by using its own `ContractGraphLoader.publish_all` under a lock instead of the refresh pipeline. That design choice is in the graph_loader docstring, L8-11.
- Discovery edges are bare `{_from,_to,confidence,rule}` (discovery.py L42, L469-481). They have no `source_id`/`kind`, so `remove_edge_by_triple` cannot remove them.
- `ExtractDataSource` falls back to `object` when `ai-parrot-loaders` is missing (datasource.py import block, around L29-38).

