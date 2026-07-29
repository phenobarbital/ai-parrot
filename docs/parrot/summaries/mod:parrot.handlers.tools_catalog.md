---
type: Wiki Summary
title: parrot.handlers.tools_catalog
id: mod:parrot.handlers.tools_catalog
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for the tool catalog endpoint (FEAT-149 TASK-1039).
relates_to:
- concept: class:parrot.handlers.tools_catalog.ToolCatalogHandler
  rel: defines
- concept: mod:parrot_tools
  rel: references
---

# `parrot.handlers.tools_catalog`

Handler for the tool catalog endpoint (FEAT-149 TASK-1039).

Exposes the ``parrot_tools.TOOL_REGISTRY`` as a read-only JSON catalog so the
frontend can present available tools when configuring an ephemeral user agent.

Route:
    GET /api/v1/tools/catalog

Response::

    [
      {
        "slug": "weather",
        "dotted_path": "parrot_tools.weather.WeatherTool",
        "description": "Get the current weather for a location."
      },
      ...
    ]

Items are sorted by ``slug`` for deterministic responses.

## Classes

- **`ToolCatalogHandler(BaseView)`** — Read-only handler that returns the global tool registry as JSON.
