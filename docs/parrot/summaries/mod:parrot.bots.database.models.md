---
type: Wiki Summary
title: parrot.bots.database.models
id: mod:parrot.bots.database.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.bots.database.models
relates_to:
- concept: class:parrot.bots.database.models.Completeness
  rel: defines
- concept: class:parrot.bots.database.models.DatabaseResponse
  rel: defines
- concept: class:parrot.bots.database.models.OutputComponent
  rel: defines
- concept: class:parrot.bots.database.models.OutputFormat
  rel: defines
- concept: class:parrot.bots.database.models.QueryDataset
  rel: defines
- concept: class:parrot.bots.database.models.QueryExecutionRequest
  rel: defines
- concept: class:parrot.bots.database.models.QueryExecutionResponse
  rel: defines
- concept: class:parrot.bots.database.models.QueryIntent
  rel: defines
- concept: class:parrot.bots.database.models.QueryResponse
  rel: defines
- concept: class:parrot.bots.database.models.RouteDecision
  rel: defines
- concept: class:parrot.bots.database.models.SchemaMetadata
  rel: defines
- concept: class:parrot.bots.database.models.TableMetadata
  rel: defines
- concept: class:parrot.bots.database.models.UserRole
  rel: defines
- concept: func:parrot.bots.database.models.components_from_string
  rel: defines
- concept: func:parrot.bots.database.models.customize_components
  rel: defines
- concept: func:parrot.bots.database.models.get_default_components
  rel: defines
- concept: mod:parrot.bots.data
  rel: references
---

# `parrot.bots.database.models`

## Classes

- **`UserRole(str, Enum)`** — Define user roles with specific output preferences.
- **`OutputComponent(Flag)`** — Flags for different response components - allows combinations.
- **`OutputFormat(str, Enum)`** — Defines the desired format of the response.
- **`QueryIntent(str, Enum)`** — Defines the user's query intents for comprehensive database operations.
- **`Completeness(IntEnum)`** — Completeness level of a cached TableMetadata entry.
- **`SchemaMetadata`** — Metadata for a single schema (client).
- **`TableMetadata`** — Enhanced table metadata for large-scale operations.
- **`QueryExecutionRequest(BaseModel)`** — Structured input for query execution.
- **`QueryExecutionResponse(BaseModel)`** — Structured output from query execution.
- **`QueryDataset(BaseModel)`** — Result dataset for a single executed query.
- **`QueryResponse(BaseModel)`** — Structured LLM output for DatabaseAgent.ask().
- **`RouteDecision`** — Query routing decision for schema-centric operations.
- **`DatabaseResponse`** — Component-based database response.

## Functions

- `def get_default_components(user_role: UserRole) -> OutputComponent` — Get default output components for a user role.
- `def customize_components(base_role: UserRole, add: Optional[OutputComponent]=None, remove: Optional[OutputComponent]=None) -> OutputComponent` — Customize output components based on base role.
- `def components_from_string(components_str: str) -> OutputComponent` — Parse components from comma-separated string.
