---
id: F009
query_id: Q009
type: read
intent: schema.py models — PropertyDef type Literal (list/dict?), RelationDef.properties shape, DiscoveryConfig, TraversalPattern, AuthorizationSpec/Rule kinds, extra=forbid
executed_at: 2026-09-24T23:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F009 — Ontology Pydantic schema: typed edge props are declarable, list/dict are untyped containers

## Summary
`PropertyDef.type` is `Literal["string","int","float","boolean","date","list","dict"]`. So `versions[]` and `steps[]` can be declared as `list`, but nothing describes or validates the items. `RelationDef.properties` is `list[dict[str, PropertyDef]]`, the same shape as `EntityDef.properties`, so `has_step.order:int`, `requires_part.quantity:int` and `t_start:float` can all be declared. Declaration is the only effect; nothing enforces these properties at write time. Every model sets `extra="forbid"`, so any unknown key in `procedures.ontology.yaml` fails validation. `AuthorizationRule.rule` accepts five values: target_is_self, target_in_management_chain, has_role (needs `role`), same_department, always.

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 18-37
  symbol: `PropertyDef`
  excerpt: |
    type: Literal["string", "int", "float", "boolean", "date", "list", "dict"]
    required: bool = False
    unique: bool = False
    default: Any = None
    enum: list[str] | None = None
    description: str | None = None
    model_config = ConfigDict(extra="forbid")
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 40-77
  symbol: `EntityDef`
  excerpt: |
    collection: str | None = None
    source: str | None = None
    key_field: str | None = None
    properties: list[dict[str, PropertyDef]] = Field(default_factory=list)
    vectorize: list[str] = Field(default_factory=list)
    extend: bool = False
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 67-70
  symbol: `EntityDef._validate_key_field`
  excerpt: |
    if v is not None and not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", v):
        raise ValueError(...)
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 80-111
  symbol: `DiscoveryRule, DiscoveryConfig`
  excerpt: |
    match_type: Literal["exact", "fuzzy", "ai_assisted", "composite"] = "exact"
    threshold: float = 0.85
    strategy: Literal["field_match", "ai_assisted", "composite"] = "field_match"
    rules: list[DiscoveryRule] = Field(default_factory=list)
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 114-136
  symbol: `RelationDef`
  excerpt: |
    from_entity: str = Field(alias="from")
    to_entity: str = Field(alias="to")
    edge_collection: str
    properties: list[dict[str, PropertyDef]] = Field(default_factory=list)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 176-209
  symbol: `AuthorizationRule`
  excerpt: |
    rule: Literal["target_is_self", "target_in_management_chain",
                  "has_role", "same_department", "always"]
    role: str | None = None
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 212-226
  symbol: `AuthorizationSpec`
  excerpt: |
    rules: list[AuthorizationRule] = Field(default_factory=list)
    default_deny: bool = True
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 142-173
  symbol: `EntityExtractionRule`
  excerpt: |
    scope: Literal["same_tenant", "same_department", "anywhere"] = "same_tenant"
    ambiguity_strategy: Literal["ask_user", "pick_first", "use_context", "fail", "rerank_by_authority"] = "ask_user"
    required: bool = True
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 261-295
  symbol: `TraversalPattern`
  excerpt: |
    description: str
    trigger_intents: list[str] = Field(default_factory=list)
    query_template: str
    post_action: Literal["vector_search", "tool_call", "none"] = "none"
    entity_extraction: dict[str, EntityExtractionRule] = Field(default_factory=dict)
    authorization: AuthorizationSpec | None = None
    tool_call: ToolCallSpec | None = None
- path: `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`
  lines: 419-446
  symbol: `OntologyDefinition`
  excerpt: |
    name: str
    version: str = "1.0"
    extends: str | None = None
    entities / relations / traversal_patterns / search_views: dict[...]
    model_config = ConfigDict(extra="forbid")

## Notes
- No `float`-with-range, `datetime`, or item types exist. `illustrated_by.confidence` is fine as a plain `float`. `t_start`/`t_end` should use `float`, not a time type.
- `OntologyDefinition` has no top-level `authorization` key. Adding one fails because of `extra="forbid"`.
- `AuthorizationRule` has no "public"/"field_tech" rule kind. Use `has_role` with a role name, or `always`.

