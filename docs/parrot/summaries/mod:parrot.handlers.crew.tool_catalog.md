---
type: Wiki Summary
title: parrot.handlers.crew.tool_catalog
id: mod:parrot.handlers.crew.tool_catalog
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Curated tool catalog for the crew builder UI.
relates_to:
- concept: class:parrot.handlers.crew.tool_catalog.CrewToolCatalogHandler
  rel: defines
---

# `parrot.handlers.crew.tool_catalog`

Curated tool catalog for the crew builder UI.

Exposes a hand-picked list of tools/toolkits that the frontend can present
when configuring agents inside a crew.  Each entry carries display metadata
and an optional JSON Schema fragment for user-configurable parameters.

Route:
    GET /api/v1/crew/tools

## Classes

- **`CrewToolCatalogHandler(BaseView)`** — Returns the curated tool catalog for the crew builder UI.
