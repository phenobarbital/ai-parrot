---
id: F004
query: "CrewDefinition and related Pydantic models"
type: read
file: packages/ai-parrot/src/parrot/handlers/crew/models.py
lines: 1-118
---

Models live in `parrot/handlers/crew/models.py` — tightly coupled to HTTP layer.

- ExecutionMode(str, Enum): sequential, parallel, flow, loop
- AgentDefinition(BaseModel): agent_id, agent_class, name, config (Dict), tools (List[str]), system_prompt
- FlowRelation(BaseModel): source, target (Union[str, List[str]])
- CrewDefinition(BaseModel): crew_id, tenant, name, description, execution_mode,
  agents (List[AgentDefinition]), flow_relations, shared_tools, max_parallel_tasks,
  metadata, created_at, updated_at

These models are imported by: handler.py, redis_persistence.py, manager.py,
autonomous/orchestrator.py — proving they are not HTTP-specific.
