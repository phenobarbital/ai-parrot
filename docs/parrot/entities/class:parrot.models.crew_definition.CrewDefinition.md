---
type: Wiki Entity
title: CrewDefinition
id: class:parrot.models.crew_definition.CrewDefinition
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Complete definition of an AgentCrew.
---

# CrewDefinition

Defined in [`parrot.models.crew_definition`](../summaries/mod:parrot.models.crew_definition.md).

```python
class CrewDefinition(BaseModel)
```

Complete definition of an AgentCrew.

Attributes:
    crew_id: Unique identifier for this crew definition (auto-generated).
    tenant: Tenant identifier for crew isolation in multi-tenant deployments.
    name: Display name of the crew.
    description: Optional human-readable description of the crew's purpose.
    execution_mode: How the crew should execute its agents.
    agents: Ordered list of agent definitions.
    tool_nodes: Deterministic tool-execution nodes (no LLM) that
        participate in the crew alongside agents.
    flow_relations: Directed dependency edges used when ``execution_mode``
        is ``FLOW``. Ignored for other modes.
    shared_tools: Tool names that are shared across all agents.
    max_parallel_tasks: Semaphore limit for concurrent agent executions.
    generate_infographic: Opt-in flag (FEAT-308) that, when ``True``, has
        the crew build an end-of-run multi-tab infographic artifact and
        attach it to ``FlowResult.infographic``. Wired through to
        ``AgentCrew`` by ``from_definition``.
    result_agent_name: Registered name of the ResultAgent used to author
        the infographic's executive-summary tab. Only relevant when
        ``generate_infographic`` is ``True``.
    metadata: Arbitrary extra data attached to the definition.
    created_at: Timestamp when this definition was created.
    updated_at: Timestamp of the most recent update.
