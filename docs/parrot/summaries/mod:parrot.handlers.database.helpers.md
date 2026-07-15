---
type: Wiki Summary
title: parrot.handlers.database.helpers
id: mod:parrot.handlers.database.helpers
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: HTTP handler exposing DatabaseAgent metadata for frontend interaction.
relates_to:
- concept: class:parrot.handlers.database.helpers.DatabaseDriversHandler
  rel: defines
- concept: class:parrot.handlers.database.helpers.DatabaseFormatsHandler
  rel: defines
- concept: class:parrot.handlers.database.helpers.DatabaseIntentsHandler
  rel: defines
- concept: class:parrot.handlers.database.helpers.DatabaseRolesHandler
  rel: defines
- concept: class:parrot.handlers.database.helpers.DatabaseSchemasHandler
  rel: defines
- concept: mod:parrot.bots.database.agent
  rel: references
- concept: mod:parrot.bots.database.models
  rel: references
---

# `parrot.handlers.database.helpers`

HTTP handler exposing DatabaseAgent metadata for frontend interaction.

Provides REST endpoints for database agent configuration data:
- GET /api/v1/agents/database/roles          - List UserRole enum values
- GET /api/v1/agents/database/formats        - List OutputFormat enum values
- GET /api/v1/agents/database/intents        - List QueryIntent enum values
- GET /api/v1/agents/database/drivers        - List supported database drivers
- GET /api/v1/agents/database/schemas        - List cached schema metadata
- GET /api/v1/agents/database/schemas/{name} - Detail for a single cached schema

## Classes

- **`DatabaseRolesHandler(BaseView)`** — Return the list of available ``UserRole`` values.
- **`DatabaseFormatsHandler(BaseView)`** — Return the list of available ``OutputFormat`` values.
- **`DatabaseIntentsHandler(BaseView)`** — Return the list of available ``QueryIntent`` values.
- **`DatabaseDriversHandler(BaseView)`** — Return the list of supported database drivers.
- **`DatabaseSchemasHandler(BaseView)`** — Return cached schema metadata from a running ``DatabaseAgent``.
