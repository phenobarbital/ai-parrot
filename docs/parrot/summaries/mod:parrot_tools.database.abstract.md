---
type: Wiki Summary
title: parrot_tools.database.abstract
id: mod:parrot_tools.database.abstract
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot_tools.database.abstract
relates_to:
- concept: class:parrot_tools.database.abstract.AbstractSchemaManagerTool
  rel: defines
- concept: class:parrot_tools.database.abstract.SchemaSearchArgs
  rel: defines
- concept: mod:parrot.stores.abstract
  rel: references
- concept: mod:parrot_tools.abstract
  rel: references
- concept: mod:parrot_tools.database.cache
  rel: references
- concept: mod:parrot_tools.database.models
  rel: references
---

# `parrot_tools.database.abstract`

## Classes

- **`SchemaSearchArgs(AbstractToolArgsSchema)`** — Arguments for schema search tool.
- **`AbstractSchemaManagerTool(AbstractTool, ABC)`** — Abstract base for database-specific schema management tools.
