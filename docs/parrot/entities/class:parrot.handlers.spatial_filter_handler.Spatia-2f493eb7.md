---
type: Wiki Entity
title: SpatialFilterEnvelope
id: class:parrot.handlers.spatial_filter_handler.SpatialFilterEnvelope
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Typed AgenTalk pass-through envelope for spatial filter requests.
---

# SpatialFilterEnvelope

Defined in [`parrot.handlers.spatial_filter_handler`](../summaries/mod:parrot.handlers.spatial_filter_handler.md).

```python
class SpatialFilterEnvelope(BaseModel)
```

Typed AgenTalk pass-through envelope for spatial filter requests.

Forwards to ``DatasetManager.spatial_filter`` WITHOUT invoking the agent
loop (``AbstractBot.run()``), conversation memory, or session history.

This is a typed pass-through only: the chat UI sends a map selection (or
reads a map reference from a previous LLM turn) and forwards the spec
directly to the filter — no agent reasoning cycle.

Attributes:
    spec: The spatial filter spec (point, radius, datasets).
    agent_id: Identifier for the agent whose DatasetManager to use.
    cap_per_dataset: Hard cap on returned features per dataset.
    channel: Originating channel (defaults to ``"agentalk"``).

## Methods

- `async def forward(self, dataset_manager: 'DatasetManager') -> 'SpatialFeatureCollection'` — Forward the spec to DatasetManager.spatial_filter.
