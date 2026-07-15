---
type: Wiki Summary
title: parrot.bots.database.toolkits.base
id: mod:parrot.bots.database.toolkits.base
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DatabaseToolkit — abstract base for all database toolkits.
relates_to:
- concept: class:parrot.bots.database.toolkits.base.DatabaseToolkit
  rel: defines
- concept: class:parrot.bots.database.toolkits.base.DatabaseToolkitConfig
  rel: defines
- concept: mod:parrot.bots.database.cache
  rel: references
- concept: mod:parrot.bots.database.models
  rel: references
- concept: mod:parrot.bots.database.retries
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.bots.database.toolkits.base`

DatabaseToolkit — abstract base for all database toolkits.

Inherits from ``AbstractToolkit`` (auto-generates tools from public async
methods) and adds the database-specific lifecycle: connect, search schema,
execute queries, cache integration.

## Classes

- **`DatabaseToolkitConfig(BaseModel)`** — Configuration passed to toolkit constructors.
- **`DatabaseToolkit(AbstractToolkit, ABC)`** — Abstract base class for all database toolkits.
