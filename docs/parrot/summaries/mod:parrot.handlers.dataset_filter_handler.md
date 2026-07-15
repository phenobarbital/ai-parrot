---
type: Wiki Summary
title: parrot.handlers.dataset_filter_handler
id: mod:parrot.handlers.dataset_filter_handler
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Dataset common-field filter HTTP handler and AgenTalk envelope (FEAT-225
  Module 7).
relates_to:
- concept: class:parrot.handlers.dataset_filter_handler.DatasetFilterEnvelope
  rel: defines
- concept: class:parrot.handlers.dataset_filter_handler.DatasetFilterHandler
  rel: defines
- concept: mod:parrot.tools.dataset_manager.filtering.contracts
  rel: references
- concept: mod:parrot.tools.dataset_manager.tool
  rel: references
---

# `parrot.handlers.dataset_filter_handler`

Dataset common-field filter HTTP handler and AgenTalk envelope (FEAT-225 Module 7).

Three endpoints:

1. **GET .../filters/{agent_id}/schema** → ``DatasetManager.get_filter_schema()``
   Returns the filter catalog for the frontend to build combo selectors.

2. **GET .../filters/{agent_id}/values/{name}** → ``DatasetManager.get_filter_values(name)``
   Returns distinct values for a named filter (combo data).

3. **POST .../filters/{agent_id}** → ``DatasetManager.apply_filters(request, persist)``
   Applies a filter request recursively across all matching datasets.

AgenTalk typed pass-through envelope (``DatasetFilterEnvelope``) mirrors
``SpatialFilterEnvelope`` — forwards directly to the manager WITHOUT invoking
the agent loop or conversation memory.

Usage (aiohttp / navigator)::

    from parrot.handlers.dataset_filter_handler import DatasetFilterHandler
    app.router.add_route("*", "/api/v1/filters/{agent_id}", DatasetFilterHandler)
    app.router.add_route("*", "/api/v1/filters/{agent_id}/schema", DatasetFilterHandler)
    app.router.add_route("*", "/api/v1/filters/{agent_id}/values/{name}", DatasetFilterHandler)

AgenTalk envelope usage::

    from parrot.handlers.dataset_filter_handler import DatasetFilterEnvelope
    envelope = DatasetFilterEnvelope(request={"region": "North"}, agent_id="my-agent")
    result = await envelope.forward(dataset_manager)

Note: This handler uses aiohttp and is intended for the ``ai-parrot-server`` package.
``DatasetManager`` is imported lazily at runtime to avoid circular dependencies.

## Classes

- **`DatasetFilterEnvelope(BaseModel)`** — Typed AgenTalk pass-through envelope for common-field filter requests.
- **`DatasetFilterHandler`** — aiohttp handler for common-field filter endpoints.
