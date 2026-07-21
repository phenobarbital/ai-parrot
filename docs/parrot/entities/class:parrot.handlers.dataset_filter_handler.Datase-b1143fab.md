---
type: Wiki Entity
title: DatasetFilterEnvelope
id: class:parrot.handlers.dataset_filter_handler.DatasetFilterEnvelope
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Typed AgenTalk pass-through envelope for common-field filter requests.
---

# DatasetFilterEnvelope

Defined in [`parrot.handlers.dataset_filter_handler`](../summaries/mod:parrot.handlers.dataset_filter_handler.md).

```python
class DatasetFilterEnvelope(BaseModel)
```

Typed AgenTalk pass-through envelope for common-field filter requests.

Forwards to ``DatasetManager.apply_filters`` WITHOUT invoking the agent
loop (``AbstractBot.run()``), conversation memory, or session history.

Attributes:
    request: Filter request mapping — ``{filter_name: value | FilterCondition}``.
    agent_id: Identifier for the agent whose DatasetManager to use.
    persist: When True, register filtered datasets back into the manager.
    channel: Originating channel (defaults to ``"agentalk"``).

## Methods

- `async def forward(self, dataset_manager: 'DatasetManager') -> 'FilterResult'` — Forward the request to DatasetManager.apply_filters.
