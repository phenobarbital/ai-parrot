---
type: Wiki Entity
title: MatrixAppServiceConfig
id: class:parrot.integrations.matrix.models.MatrixAppServiceConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for Matrix Application Service mode.
---

# MatrixAppServiceConfig

Defined in [`parrot.integrations.matrix.models`](../summaries/mod:parrot.integrations.matrix.models.md).

```python
class MatrixAppServiceConfig(BaseModel)
```

Configuration for Matrix Application Service mode.

## Methods

- `def bot_mxid(self) -> str` — Full MXID of the AS bot user.
- `def agent_mxid(self, agent_name: str) -> str` — Full MXID for a named agent.
