---
id: F014
query_id: Q034
type: read
intent: "Read the crew definition / models module found by Q033 (or crew.py from_definition region)."
executed_at: 2026-10-30T16:44:46Z
duration_ms: 400
parent_id: null
depth: 0
merged_from: [FC-015-agentcrew-from-definition, FW-016-crew-definition-roles]
---

# F014 — `AgentCrew.from_definition()` resolves agent classes and tools via injected `class_resolver`/`tool_resolver` callables (BasicAgent fallback)

## Summary

*[FC-015-agentcrew-from-definition]* `crew.py` line 781: classmethod taking `crew_def`, keyword-only `class_resolver: Callable[[str], Optional[type]]`, optional `tool_resolver`, `google_api_key`, **kwargs. Unknown class → `BasicAgent`. This resolver-injection seam is where an "expert resolver" (name → expert bundle → configured Agent) would plug in without changing the crew engine.

*[FW-016-crew-definition-roles]* Crew definition models were relocated to `parrot/models/crew_definition.py` (TASK-1060) and consumed by `AgentCrew.from_definition()` (TASK-1061; `bots/flows/crew/crew.py`). `AgentDefinition` is `extra="forbid"` with `agent_id`, `agent_class` (default "BaseAgent"), `name`, `config` (kwargs), `tools`, `system_prompt`. `CrewDefinition` adds `tenant` (default "global"), `shared_tools`, `max_parallel_tasks`, infographic/result-agent options, `enable_execution_wiki` (per-crew execution wiki in a `WikiStore` at `.parrot/crew_wiki/<slug>`), and validators `validate_flow_relations` (aliases agent_id→name) and `validate_acyclic` (Kahn). Server side: `BotManager._create_crew_from_definition` and the REST `CrewHandler` (`handlers/crew/handler.py`) build crews from stored definitions.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: 781-800
  symbol: `AgentCrew.from_definition`
  excerpt: |
    def from_definition(cls, crew_def: "CrewDefinition", *,
        class_resolver: Callable[[str], Optional[type]],
        tool_resolver: Optional[Callable[[str], Optional[AbstractTool]]] = None,
        google_api_key: Optional[str] = None, **kwargs) -> "AgentCrew":
        """... When it returns None the agent falls back to BasicAgent."""

- path: `packages/ai-parrot/src/parrot/models/crew_definition.py`
  lines: 1-260
  symbol: `ExecutionMode` / `AgentDefinition` / `CrewDefinition`
  wiki_page_id: file:packages/ai-parrot/src/parrot/models/crew_definition.py
  score: 31.71
  excerpt: |
    class ExecutionMode(str, Enum): SEQUENTIAL="sequential"; PARALLEL="parallel"; FLOW="flow"; LOOP="loop"
    class AgentDefinition(BaseModel):
        model_config = ConfigDict(extra="forbid")
        agent_id: str; agent_class: str = "BaseAgent"; name: Optional[str]
        config: Dict[str, Any]; tools: List[str]; system_prompt: Optional[str]
    class CrewDefinition(BaseModel):
        tenant: str = "global"; execution_mode: ExecutionMode; agents: List[AgentDefinition]
        tool_nodes: List[ToolNodeDefinition]; flow_relations: List[FlowRelation]
        enable_execution_wiki: bool = True; execution_wiki_path: Optional[str]  # {cwd}/.parrot/crew_wiki/<crew-slug>

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  symbol: `AgentCrew.from_definition`
  wiki_page_id: file:packages/ai-parrot/src/parrot/bots/flows/crew/crew.py
  score: 30.76
  excerpt: |
    AgentCrew — Parallel, Sequential, Flow, and Loop-Based Execution.

- path: `packages/ai-parrot-server/src/parrot/manager/manager.py`
  symbol: `BotManager._create_crew_from_definition`
  wiki_page_id: sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager._create_crew_from_definition
  score: 1.00
  excerpt: |
    Create an AgentCrew from a CrewDefinition.

## Notes

*[FC-015-agentcrew-from-definition]* Server-side wrapper: `BotManager._create_crew_from_definition` (ai-parrot-server, from wiki orientation).

*[FW-016-crew-definition-roles]* `AgentDefinition.agent_class` + `config` is how a crew names a registered agent class today — an expert could be referenced by `agent_class="DomainExpert", config={"expert": "cve-analyst"}` without changing the model, but `extra="forbid"` means `lead/support/mode` cannot be added ad hoc. The `execution_mode` set lacks the source's hub-and-spoke "subagent" and "mob" modes; `parallel` + a lead integration step is the closest composition. `.parrot/crew_wiki/` is an existing `.parrot/` workspace convention.
