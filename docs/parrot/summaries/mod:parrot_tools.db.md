---
type: Wiki Summary
title: parrot_tools.db
id: mod:parrot_tools.db
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Unified Database Tool for AI-Parrot
relates_to:
- concept: class:parrot_tools.db.DatabaseFlavor
  rel: defines
- concept: class:parrot_tools.db.DatabaseTool
  rel: defines
- concept: class:parrot_tools.db.DatabaseToolArgs
  rel: defines
- concept: class:parrot_tools.db.OutputFormat
  rel: defines
- concept: class:parrot_tools.db.QueryType
  rel: defines
- concept: class:parrot_tools.db.QueryValidationResult
  rel: defines
- concept: class:parrot_tools.db.SchemaMetadata
  rel: defines
- concept: mod:parrot.clients.base
  rel: references
- concept: mod:parrot.clients.factory
  rel: references
- concept: mod:parrot.models
  rel: references
- concept: mod:parrot.stores.abstract
  rel: references
- concept: mod:parrot_tools.abstract
  rel: references
---

# `parrot_tools.db`

Unified Database Tool for AI-Parrot

Consolidates schema extraction, knowledge base building, query generation,
validation, and execution into a single, powerful database interface.

## Classes

- **`DatabaseFlavor(str, Enum)`** — Supported database flavors.
- **`QueryType(str, Enum)`** — Supported query types.
- **`OutputFormat(str, Enum)`** — Supported output formats.
- **`SchemaMetadata(BaseModel)`** — Metadata for a database schema.
- **`QueryValidationResult(BaseModel)`** — Result of query validation.
- **`DatabaseToolArgs(AbstractToolArgsSchema)`** — Arguments for the unified database tool.
- **`DatabaseTool(AbstractTool)`** — Unified Database Tool that handles the complete database interaction pipeline:
