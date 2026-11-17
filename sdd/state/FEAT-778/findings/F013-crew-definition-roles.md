---
id: F013
query_id: Q033
type: grep
intent: "Locate CrewDefinition and crew agent role models (lead/support/dispatch mode precedent)."
executed_at: 2026-10-30T16:44:46Z
duration_ms: 500
parent_id: null
depth: 0
merged_from: [FC-014-crew-definition-roles]
---

# F013 — `CrewDefinition`/`AgentDefinition` live in `parrot/models/crew_definition.py`; agents are an ordered list with `execution_mode` + `flow_relations`, no lead/support role field

## Summary

`AgentDefinition` (line 31): agent_id, agent_class, name, config (**kwargs), tools, system_prompt. `CrewDefinition` (line 178): crew_id, tenant, name, description, execution_mode, agents, tool_nodes, flow_relations, shared_tools, max_parallel_tasks, infographic opts, enable_execution_wiki/execution_wiki_path, metadata. Dispatch shape (sequential/parallel/flow/loop) is there, but "lead/support/mutually blind contributions" is not; there is no role enum in `bots/flows/crew/` (only `CrewAgentNode`).

## Citations

- path: `packages/ai-parrot/src/parrot/models/crew_definition.py`
  lines: 31-60
  symbol: `AgentDefinition`
  excerpt: |
    class AgentDefinition(BaseModel):
        agent_id: str; agent_class: str; name: Optional[str]; config: Dict[str, Any]
        tools: List[str]; system_prompt: Optional[str]

- path: `packages/ai-parrot/src/parrot/models/crew_definition.py`
  lines: 178-215
  symbol: `CrewDefinition`
  excerpt: |
    crew_id, tenant, name, description, execution_mode, agents, tool_nodes,
    flow_relations, shared_tools, max_parallel_tasks, generate_infographic,
    result_agent_name, infographic_theme, enable_execution_wiki, execution_wiki_path, metadata

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/nodes.py`
  lines: 28
  symbol: `CrewAgentNode`
  excerpt: |
    class CrewAgentNode(_CoreAgentNode):

## Notes

`tenant` on CrewDefinition is a third tenancy precedent (with skills and bookstore scope).
