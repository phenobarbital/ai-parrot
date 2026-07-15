---
type: Wiki Entity
title: InfographicRenderResult
id: class:parrot.tools.infographic_toolkit.InfographicRenderResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Envelope returned by InfographicToolkit.render (return_direct=True).
---

# InfographicRenderResult

Defined in [`parrot.tools.infographic_toolkit`](../summaries/mod:parrot.tools.infographic_toolkit.md).

```python
class InfographicRenderResult(BaseModel)
```

Envelope returned by InfographicToolkit.render (return_direct=True).

Consumed by ``PandasAgent.ask()``'s post-loop branch via isinstance check.
