---
type: Wiki Entity
title: DataAnalystHandler
id: class:parrot.handlers.agents.data.DataAnalystHandler
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Handler for creating in-memory empty PandasAgent instances.
---

# DataAnalystHandler

Defined in [`parrot.handlers.agents.data`](../summaries/mod:parrot.handlers.agents.data.md).

```python
class DataAnalystHandler(BaseView)
```

Handler for creating in-memory empty PandasAgent instances.

This handles spinning up instances of empty PandasAgents which are 
used for in-session data analysis (Dataframes can be appended later).
These agents are intentionally ephemeral and not persistent unless specified.

## Methods

- `async def post(self, request: web.Request) -> web.Response`
