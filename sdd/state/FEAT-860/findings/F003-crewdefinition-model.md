---
id: F003
query_id: Q009
type: read
intent: "Read the CrewDefinition model: identity fields (crew_id, name, tenant), extra=forbid, serialization."
executed_at: 2026-11-09T17:20:30Z
duration_ms: 800
parent_id: null
depth: 0
merged_from: [FC-004]
---

# F003 — CrewDefinition (core, `parrot.models.crew_definition`): crew_id uuid4 str, tenant default "global", name required, all models extra="forbid"

## Summary

`CrewDefinition` lives in CORE (`packages/ai-parrot/src/parrot/models/crew_definition.py`, 496 lines) and is
re-exported by the server's `handlers/crew/models.py`. Identity: `crew_id: str` (uuid4 default_factory),
`tenant: str = "global"`, `name: str` (required). Persistable scalar columns: `description`,
`execution_mode` (enum), `max_parallel_tasks`, `generate_infographic`, `result_agent_name`,
`infographic_theme`, `enable_execution_wiki`, `execution_wiki_path`, `metadata` (dict), `created_at` /
`updated_at` (tz-aware UTC defaults). Nested lists `agents` (AgentDefinition), `tool_nodes`,
`flow_relations`. `CrewDefinition`, `AgentDefinition`, `ToolNodeDefinition`, `FlowRelation` all use
`ConfigDict(extra="forbid")`; model validators check flow relations + acyclicity. The LLM lives in
`AgentDefinition.config: Dict[str, Any]` (free-form, forwarded as `**kwargs`).

## Citations

- path: `packages/ai-parrot/src/parrot/models/crew_definition.py`
  lines: 31-70
  symbol: `AgentDefinition`
  excerpt: |
    class AgentDefinition(BaseModel):
        model_config = ConfigDict(extra="forbid")
        agent_id: str
        agent_class: str = "BaseAgent"
        name: Optional[str] = None
        config: Dict[str, Any] = Field(default_factory=dict, description="Agent configuration (llm, model, temperature, etc.)")
        tools: List[str] = Field(default_factory=list)
        system_prompt: Optional[str] = None

- path: `packages/ai-parrot/src/parrot/models/crew_definition.py`
  lines: 216-224
  symbol: `CrewDefinition.crew_id / tenant / name`
  excerpt: |
    crew_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique identifier for the crew")
    tenant: str = Field(default="global", description="Tenant identifier for crew isolation")
    name: str = Field(description="Name of the crew")

- path: `packages/ai-parrot/src/parrot/models/crew_definition.py`
  lines: 225-304
  symbol: `CrewDefinition fields`
  excerpt: |
    description: Optional[str]; execution_mode: ExecutionMode = SEQUENTIAL
    agents: List[AgentDefinition]; tool_nodes: List[ToolNodeDefinition]; flow_relations: List[FlowRelation]
    shared_tools: List[str]; max_parallel_tasks: int = 10
    generate_infographic: bool = False; result_agent_name: str = "result-agent"; infographic_theme: Optional[str]
    enable_execution_wiki: bool = True; execution_wiki_path: Optional[str]
    metadata: Dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

- path: `packages/ai-parrot/src/parrot/models/crew_definition.py`
  lines: 306-309
  symbol: `CrewDefinition.model_config`
  excerpt: |
    model_config = ConfigDict(
        extra="forbid",
        json_encoders={datetime: lambda v: v.isoformat()},
    )

- path: `packages/ai-parrot/src/parrot/models/crew_definition.py`
  lines: 376-443
  symbol: `CrewDefinition.validate_flow_relations / validate_acyclic`
  excerpt: |
    @model_validator(mode="after")
    def validate_flow_relations(self) -> "CrewDefinition": ...
    @model_validator(mode="after")
    def validate_acyclic(self) -> "CrewDefinition": ...

- path: `packages/ai-parrot-server/src/parrot/handlers/crew/models.py`
  lines: 7-22
  symbol: `re-export of CrewDefinition`
  excerpt: |
    CrewDefinition) now live in ``parrot.models.crew_definition`` and are
    from parrot.models.crew_definition import (  # noqa: F401
        CrewDefinition,

## Notes

- Timezone inconsistency: model defaults are tz-aware (`datetime.now(timezone.utc)`) but
  `CrewRedis.save_crew` overwrites `updated_at = datetime.utcnow()` (naive) — see FC-001. A `timestamptz`
  column needs a normalization rule (assume naive = UTC).
- Model validators run on every rehydration; a stored crew with a now-invalid flow fails to load — the
  `_strip_unknown_keys` compat step only handles unknown keys, not invalid values.
- Because the body is fully typed, a table can either store the whole `model_dump(mode="json")` as one
  `jsonb` column (Redis-equivalent, schema-drift tolerant) or promote identity/search columns
  (`crew_id`, `tenant`, `name`, `description`, `execution_mode`, timestamps) next to the jsonb payload.
