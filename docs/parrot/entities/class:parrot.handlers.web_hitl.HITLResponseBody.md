---
type: Wiki Entity
title: HITLResponseBody
id: class:parrot.handlers.web_hitl.HITLResponseBody
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Request body for ``POST /api/v1/agents/hitl/respond``.
---

# HITLResponseBody

Defined in [`parrot.handlers.web_hitl`](../summaries/mod:parrot.handlers.web_hitl.md).

```python
class HITLResponseBody(BaseModel)
```

Request body for ``POST /api/v1/agents/hitl/respond``.

Attributes:
    interaction_id: UUID of the pending interaction to resolve.
    value: The human's response value (type depends on ``interaction_type``).
    response_type: Optional override for the response type. Defaults to the
        interaction's declared type.
