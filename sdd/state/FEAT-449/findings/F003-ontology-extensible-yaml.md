---
id: F003
query_id: Q002
type: read
intent: Determine whether the graph collection vocabulary is closed or extensible (does the legal vocabulary require a fork?)
executed_at: 2026-08-23T00:21:02Z
depth: 1
parent_id: F002
---

# F003 — Graph vocabulary is a declarative YAML ontology; custom legal collections are a supported extension point

## Summary

GraphIndex ships a **closed** meta-ontology of 9 entity types and 10 relation types mapped to
fixed `gi_*` collections — none of the legal kinds (`norma`, `articulo`, `sentencia`, `modifica`,
`deroga`, `cita`…) exist. Crucially, that meta-ontology is explicitly documented as *additive*
and is merged into a **per-tenant** ontology via `OntologyMerger`, which loads ontologies from
**YAML files**. `EntityDef` accepts an arbitrary `collection`, `key_field`, `properties` and
`vectorize` list, with `extend: bool` for layering. `initialize_tenant` provisions the Arango
collections automatically from the entity/relation defs. There is a shipped domain precedent:
`defaults/domains/field_services.ontology.yaml`. So a `legal.ontology.yaml` is a first-class
extension, **not** a fork of GraphIndex.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/meta_ontology.py`
  lines: 1-24
  excerpt: |
    Provides the programmatic MergedOntology-compatible definition with:
    - 9 entity types: document, section, symbol, concept, rationale, skill,
      wiki_page, run, claim
    These definitions are **additive** — they do not conflict with existing
    tenant ontologies.  They are intended to be merged at tenant initialisation
    time via OntologyMerger.

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/meta_ontology.py`
  lines: 285-312
  symbol: `COLLECTION_TO_KIND`, `KIND_TO_COLLECTION`, `EDGE_KIND_TO_COLLECTION`
  excerpt: |
    EDGE_KIND_TO_COLLECTION: dict[str, str] = {
        "contains": "gi_contains",
        "references": "gi_references",
        "supported_by": "gi_supported_by",
        "contradicts": "gi_contradicts",

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 40-64
  symbol: `EntityDef`
  excerpt: |
    class EntityDef(BaseModel):
        collection: str | None = None
        source: str | None = None
        key_field: str | None = None
        properties: list[dict[str, PropertyDef]] = Field(default_factory=list)
        vectorize: list[str] = Field(default_factory=list)
        extend: bool = False

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/merger.py`
  lines: 26-51
  symbol: `OntologyMerger.merge`
  excerpt: |
    class OntologyMerger:
        def merge(self, yaml_paths: list[Path]) -> MergedOntology:

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py`
  lines: 71
  symbol: `initialize_tenant`
  excerpt: |
    async def initialize_tenant(self, ctx: TenantContext) -> None:

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/domains/field_services.ontology.yaml`
  excerpt: |
    # the only shipped domain ontology — direct template for legal.ontology.yaml

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/base.ontology.yaml`
  lines: 1-40
  excerpt: |
    name: base
    entities:
      Employee:
        collection: employees
        key_field: employee_id
        properties:
          - employee_id:
              type: string

## Notes

This substantially de-risks §3.2/§3.3 of the source: the legal collection and edge vocabulary
is configuration, not framework surgery. It does NOT resolve OQ1 — see F002; the multiplicity
unit remains a tenant/database, not a namespace.
