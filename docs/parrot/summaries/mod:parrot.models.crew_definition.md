---
type: Wiki Summary
title: parrot.models.crew_definition
id: mod:parrot.models.crew_definition
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Core crew definition models.
relates_to:
- concept: class:parrot.models.crew_definition.AgentDefinition
  rel: defines
- concept: class:parrot.models.crew_definition.CrewDefinition
  rel: defines
- concept: class:parrot.models.crew_definition.ExecutionMode
  rel: defines
- concept: class:parrot.models.crew_definition.FlowRelation
  rel: defines
- concept: class:parrot.models.crew_definition.ToolNodeDefinition
  rel: defines
---

# `parrot.models.crew_definition`

Core crew definition models.

Defines the data structures used to describe an AgentCrew: execution modes,
agent definitions, flow relations, and complete crew definitions.

These models are intentionally placed in ``parrot/models/`` (not in the HTTP
handler layer) so they can be imported from any part of the framework —
including ``parrot/bots/`` — without creating circular dependencies.

## Classes

- **`ExecutionMode(str, Enum)`** — Execution modes for AgentCrew.
- **`AgentDefinition(BaseModel)`** — Definition of an agent in a crew.
- **`ToolNodeDefinition(BaseModel)`** — Definition of a deterministic tool-execution node in a crew.
- **`FlowRelation(BaseModel)`** — Defines a dependency relationship between agents in flow mode.
- **`CrewDefinition(BaseModel)`** — Complete definition of an AgentCrew.
