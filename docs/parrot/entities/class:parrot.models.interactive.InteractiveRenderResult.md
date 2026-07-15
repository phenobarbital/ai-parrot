---
type: Wiki Entity
title: InteractiveRenderResult
id: class:parrot.models.interactive.InteractiveRenderResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Envelope returned by ``InteractiveToolkit.render`` (return_direct=True).
---

# InteractiveRenderResult

Defined in [`parrot.models.interactive`](../summaries/mod:parrot.models.interactive.md).

```python
class InteractiveRenderResult(BaseModel)
```

Envelope returned by ``InteractiveToolkit.render`` (return_direct=True).

Mirrors ``InfographicRenderResult`` so the agent post-loop can handle both
artifact families through a single isinstance branch.
