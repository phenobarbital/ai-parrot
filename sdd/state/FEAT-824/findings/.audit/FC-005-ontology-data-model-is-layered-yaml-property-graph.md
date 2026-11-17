---
id: FC-005
query_id: Q005
type: read
intent: "What is the ontology data model in code (entities, relations, traversal patterns, source format) and how does it compare to the draft's RDF/Turtle/IRI model?"
executed_at: 2026-11-06T13:36:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-005 — The coded ontology is a layered YAML property-graph schema, not an RDF vocabulary

## Summary

`OntologyParser` loads **YAML** (`*.ontology.yaml`) into a Pydantic `OntologyDefinition` with four sections: `entities` (each = a *vertex collection* with `collection`, `source`, `key_field`, `properties`, `vectorize`, `extend`), `relations` (each = an *edge collection* with `from`/`to`/`edge_collection`/`discovery` rules), `traversal_patterns` (trigger intents + query template + post-action + entity extraction + authorization + tool-call) and `search_views` (ArangoSearch view declarations). Layers (base → domain → client) merge into `MergedOntology`, which generates the LLM schema prompt. Identifiers are **entity names, collection names and per-entity `key_field` values** — there is no IRI, no class hierarchy (`subClassOf`), no labels/SKOS, no versioned publication. It is an *instance-graph schema + query catalogue* (what data to load and how to traverse it), whereas the draft's OntologyStore is a *concept vocabulary* (classes, labels, closure). The two models overlap only in the `Concept` entity / `concept_is_a` relation (see FC-008).

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/parser.py`
  lines: 15-62
  symbol: `OntologyParser.load`
  excerpt: |
    # Path to package-bundled default ontology files
    _DEFAULTS_DIR = Path(__file__).parent / "defaults"
    ...
            with open(path, encoding="utf-8") as f:
                raw: dict[str, Any] = yaml.safe_load(f) or {}
    ...
            definition = OntologyDefinition.model_validate(raw)

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 40-63
  symbol: `EntityDef`
  excerpt: |
    class EntityDef(BaseModel):
        """Definition of a vertex collection (entity) in the ontology.
        collection: str | None = None
        source: str | None = None
        key_field: str | None = None
        properties: list[dict[str, PropertyDef]] = Field(default_factory=list)
        vectorize: list[str] = Field(default_factory=list)
        extend: bool = False
        model_config = ConfigDict(extra="forbid")

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 114-136
  symbol: `RelationDef`
  excerpt: |
    class RelationDef(BaseModel):
        """Definition of an edge collection (relation) in the ontology.
        from_entity: str = Field(alias="from")
        to_entity: str = Field(alias="to")
        edge_collection: str
        properties: list[dict[str, PropertyDef]] = Field(default_factory=list)
        discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 261-297
  symbol: `TraversalPattern`
  excerpt: |
    description: str
    trigger_intents: list[str] = Field(default_factory=list)
    query_template: str
    query_templates: dict[str, str] = Field(default_factory=dict)
    post_action: Literal["vector_search", "tool_call", "none"] = "none"
    post_query: str | None = None
    entity_extraction: dict[str, EntityExtractionRule] = Field(default_factory=dict)
    authorization: AuthorizationSpec | None = None
    tool_call: ToolCallSpec | None = None

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 421-448
  symbol: `OntologyDefinition`
  excerpt: |
    name: str
    version: str = "1.0"
    extends: str | None = None
    description: str | None = None
    entities: dict[str, EntityDef] = Field(default_factory=dict)
    relations: dict[str, RelationDef] = Field(default_factory=dict)
    traversal_patterns: dict[str, TraversalPattern] = Field(default_factory=dict)
    search_views: dict[str, SearchViewDef] = Field(default_factory=dict)

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 454-528
  symbol: `MergedOntology`
  excerpt: |
    def get_entity_collections(self) -> list[str]:
        """Return all vertex collection names."""
    def get_edge_collections(self) -> list[str]:
    def get_vectorizable_fields(self, entity_name: str) -> list[str]:
        """Return fields that should be embedded in PgVector for an entity.
    def build_schema_prompt(self) -> str:
        """Generate a natural language description of the ontology for the LLM.

- path: `packages/ai-parrot/src/parrot/knowledge/ontology/defaults/base.ontology.yaml`
  lines: 1-115
  symbol: `base` ontology (Employee / Department / Role)
  excerpt: |
    entities:
      Employee:
        collection: employees
        key_field: employee_id
        vectorize:
          - job_title
    relations:
      reports_to:
        from: Employee
        to: Employee
        edge_collection: reports_to

## Notes

- Outline of `schema.py` (688 lines): `PropertyDef` L18-37, `EntityDef` L40-77, `DiscoveryRule` L80-97, `DiscoveryConfig` L100-111, `RelationDef` L114-136, `EntityExtractionRule` L142-173, `AuthorizationRule` L176-209, `AuthorizationSpec` L212-226, `ToolCallSpec` L229-258, `TraversalPattern` L261-297, `SearchViewField/Link/Def` L300-346, `merge_link_field` L349-390, `view_properties_match` L393-418, `OntologyDefinition` L421-448, `MergedOntology` L454-528, `TenantContext` L531-546, `ResolvedIntent` L549-583, `EnrichedContext` L586-626, `ContextEnvelope` L629-688.
- Bundled ontology files: `defaults/base.ontology.yaml`, `defaults/knowledge.ontology.yaml`, `defaults/domains/{contracts,field_services,legal,procedures}.ontology.yaml`.
- The ontology in this repo models **organisational instance data** (employees, departments, norms, articles, contracts) loaded from external sources (`source: workday | jira | csv`), with relation *discovery rules* and authorization specs. None of that has a home in the draft's `ontology.concept / label / relation / closure` tables: the draft covers a different (smaller) object than `parrot.knowledge.ontology` does today.
- `search_views` + `merge_link_field` + `view_properties_match` are ArangoSearch-specific schema features living in the neutral `schema.py`.
