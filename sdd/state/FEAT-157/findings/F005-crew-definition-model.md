---
id: F005
query: "CrewDefinition model for FEAT-156 integration"
type: read
file: packages/ai-parrot/src/parrot/handlers/crew/models.py
---

## CrewDefinition (handlers/crew/models.py, lines 66-118)

Pydantic model for declarative crew definitions. Used by the autonomous
orchestrator and Redis persistence.

Fields include: `crew_id`, `tenant`, `name`, `execution_mode`, `agents`,
`flow_relations`, `shared_tools`, `max_parallel_tasks`, `metadata`.

**No hooks field exists yet.** FEAT-156 is adding `from_definition()` to
AgentCrew. Hooks could be added to `CrewDefinition` as a list of hook
references (string-based for serialization) and resolved at build time.

However, hooks are typically runtime callables, so the primary registration
should be on the AgentCrew instance, not the serialized definition.
