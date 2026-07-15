---
type: Wiki Summary
title: parrot.handlers.spatial_filter_handler
id: mod:parrot.handlers.spatial_filter_handler
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Spatial filter HTTP handler and AgenTalk pass-through envelope (FEAT-219
  Module 6).
relates_to:
- concept: class:parrot.handlers.spatial_filter_handler.DirectSpatialRequest
  rel: defines
- concept: class:parrot.handlers.spatial_filter_handler.NLSpatialRequest
  rel: defines
- concept: class:parrot.handlers.spatial_filter_handler.NLSpatialSynthesizer
  rel: defines
- concept: class:parrot.handlers.spatial_filter_handler.SpatialFilterEnvelope
  rel: defines
- concept: class:parrot.handlers.spatial_filter_handler.SpatialFilterHandler
  rel: defines
- concept: mod:parrot.tools.dataset_manager.spatial.contracts
  rel: references
- concept: mod:parrot.tools.dataset_manager.tool
  rel: references
---

# `parrot.handlers.spatial_filter_handler`

Spatial filter HTTP handler and AgenTalk pass-through envelope (FEAT-219 Module 6).

Two transport paths, both returning an identical ``SpatialFeatureCollection``:

1. **Direct (deterministic) path**: frontend POSTs ``{point, radius, unit, datasets}``
   directly → ``DatasetManager.spatial_filter(spec)`` → GeoJSON response.

2. **NL→spec synthesis path**: frontend POSTs ``{query, datasets}`` with natural
   language → ``NLSpatialSynthesizer.synthesize(query, datasets)`` builds a
   ``SpatialFilterSpec`` → same ``spatial_filter`` call → identical response.

3. **AgenTalk typed pass-through envelope**: typed ``SpatialFilterEnvelope`` wraps
   the spec for chat-originating requests.  The envelope forwards to
   ``spatial_filter`` and does NOT invoke ``AbstractBot.run()`` or the agent loop
   (spec Non-Goals: no bidirectional chat↔map coupling).

Usage (aiohttp / navigator)::

    # In your app router:
    from parrot.handlers.spatial_filter_handler import SpatialFilterHandler
    app.router.add_route("*", "/api/v1/spatial/{agent_id}", SpatialFilterHandler)
    app.router.add_route("*", "/api/v1/spatial/{agent_id}/manifest", SpatialFilterHandler)

AgenTalk envelope usage::

    from parrot.handlers.spatial_filter_handler import SpatialFilterEnvelope
    envelope = SpatialFilterEnvelope(spec=spec, agent_id="my-agent")
    result = await envelope.forward(dataset_manager)

Note: The handler uses aiohttp and is intended for the ``ai-parrot-server`` package to
mount.  It imports ``DatasetManager`` lazily at runtime to avoid circular dependencies
at module load time.

## Classes

- **`SpatialFilterEnvelope(BaseModel)`** — Typed AgenTalk pass-through envelope for spatial filter requests.
- **`NLSpatialSynthesizer`** — Thin synthesizer: natural language → SpatialFilterSpec.
- **`DirectSpatialRequest(BaseModel)`** — Request body for the direct (deterministic) spatial filter path.
- **`NLSpatialRequest(BaseModel)`** — Request body for the NL→spec synthesis spatial filter path.
- **`SpatialFilterHandler`** — aiohttp handler for spatial filter endpoints.
