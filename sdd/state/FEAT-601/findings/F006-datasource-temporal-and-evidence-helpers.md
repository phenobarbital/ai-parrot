---
id: F006
query_id: Q006
type: read
intent: ContractCardDataSource shape, as_of/version helpers, evidence validation helpers.
executed_at: 2026-09-24T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F006 — datasource, temporal and evidence helpers

## Summary
`ContractCardDataSource(ExtractDataSource)` is registered as `"contractcard"` through `DataSourceFactory.register_api_source`. It needs `config["catalog"]` to be a `ContractCatalogStore`. `extract(fields, filters)` has no EntityDef argument; it infers the entity from key-marker fields in a fixed order and returns an `ExtractionResult` of `ExtractedRecord`s. `snapshot()` returns every entity for the graph loader. On the temporal side there are two separate time notions:
- recorded time: `ContractTemporalPublisher.graph_as_of/history/diff` over the GraphIndex persistence, with the node id prefix `contracts:contract:`;
- effective time: `contract_in_force`, which delegates to `ContractVersion.in_force`.

On the evidence side, `EvidenceArchive.resolve(citation, ref)` is the check at release time: version, sha prefix, verbatim quote and page. `StagingArea` provides staging and promotion of the tree per tenant and per id.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/datasource.py`
  lines: 26-40
  symbol: optional `parrot_loaders` import
  excerpt: |
    from parrot_loaders.extractors.base import (ExtractDataSource, ExtractedRecord, ExtractionResult)
    from parrot_loaders.extractors.factory import DataSourceFactory
    _LOADERS_AVAILABLE = True
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/datasource.py`
  lines: 55-64
  symbol: `SOURCE_NAME` / `ENTITY_ROUTING_ORDER`
  excerpt: |
    SOURCE_NAME = "contractcard"
    ENTITY_ROUTING_ORDER = (("obligation_id","Obligation"),("person_id","Person"),
        ("party_id","Party"),("contract_id","Contract"),("standard_id","ComplianceStandard"))
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/datasource.py`
  lines: 144-157
  symbol: `ContractCardDataSource.__init__`
  excerpt: |
    def __init__(self, name: str = SOURCE_NAME, config: Optional[dict[str, Any]] = None) -> None:
        catalog = self.config.get("catalog")
        if not isinstance(catalog, ContractCatalogStore): raise ValueError(...)
        self.include_inactive = bool(self.config.get("include_inactive", False))
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/datasource.py`
  lines: 162-192
  symbol: `ContractCardDataSource.infer_entity`
  excerpt: |
    if not fields: return "Contract"
    for marker, entity in ENTITY_ROUTING_ORDER:
        if marker in requested: ... return entity
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/datasource.py`
  lines: 380-401
  symbol: `ContractCardDataSource.snapshot`
  excerpt: |
    return {entity: await self.records_for(entity, filters=filters)
            for entity in ("Contract", "Party", "Person", "Obligation", "ComplianceStandard")}
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/datasource.py`
  lines: 405-440
  symbol: `ContractCardDataSource.extract`
  excerpt: |
    entity = self.infer_entity(fields)
    records = await self.records_for(entity, filters=filters)
    return ExtractionResult(records=[ExtractedRecord(data=payload, metadata={"entity": entity, "source": self.name}) ...],
                            total=len(payloads), source_name=self.name, extracted_at=datetime.now(tz=timezone.utc))
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/datasource.py`
  lines: 447-455
  symbol: `register`
  excerpt: |
    DataSourceFactory.register_api_source(SOURCE_NAME, ContractCardDataSource)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/temporal.py`
  lines: 48-66
  symbol: `TEMPORAL_AGENT_ID` / `NODE_ID_PREFIX` / `contract_node_id` / `revision_run_id`
  excerpt: |
    TEMPORAL_AGENT_ID = "contracts.temporal"
    NODE_ID_PREFIX = "contracts:contract:"
    return f"contracts:{contract_id}:{version_n}:{revision}"
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/temporal.py`
  lines: 69-140
  symbol: `build_graph_update`
  excerpt: |
    def build_graph_update(card, version=None, *, tenant_id, revision=None, tombstone=False, agent_id=TEMPORAL_AGENT_ID) -> GraphUpdate:
        node = UniversalNode(node_id=contract_node_id(card.contract_id), kind=NodeKind.DOCUMENT, ..., domain_tags=domain_tags)
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/temporal.py`
  lines: 355-395
  symbol: `graph_as_of` / `contract_history` / `contract_diff` / `contract_in_force`
  excerpt: |
    async def graph_as_of(self, ctx, when: datetime): return await self.persistence.as_of(ctx, when)
    @staticmethod
    def contract_in_force(card: ContractCard, as_of) -> Optional[ContractVersion]:
        for version in sorted(card.versions, key=lambda item: (item.n, item.revision)):
            if version.in_force(as_of): return version
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/evidence.py`
  lines: 78-95
  symbol: `EvidenceRef`
  excerpt: |
    tenant_id: str; contract_id: str; version_n: int; revision: int; source_sha256: str
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/evidence.py`
  lines: 145-158
  symbol: `StagingArea`
  excerpt: |
    class StagingArea:  # published_root / staging_root; begin / promote / discard
        def __init__(self, root: str | Path, *, tenant_id: str) -> None:
- path: `packages/ai-parrot/src/parrot/knowledge/contracts/evidence.py`
  lines: 462-497
  symbol: `EvidenceArchive.resolve`
  excerpt: |
    if citation.contract_id != ref.contract_id: return EvidenceLookup(reason="citation belongs to another contract")
    quote = normalize_quote(citation.quote)
    body = await self.load_body(ref, citation.node_id)
    if quote not in normalize_quote(body): return EvidenceLookup(body=body, reason="quote is not verbatim ...")

## Notes
- `infer_entity` returns "Contract" when no fields are given. A manuals datasource needs its own routing order, e.g. `step_id` → Step, `part_id` → Part, `tool_id` → Tool, `manual_id` → Manual, most specific first.
- `EvidenceRef` and `Citation` hardcode `contract_id`. The evidence module is otherwise generic; a rename to `doc_id` would make it reusable.
- `contract_in_force` / "as of" answers questions about effective dates in a contract. For manuals the matching idea is the revision or edition that applies to a product serial. That's a new model, not a copy.
