---
type: Wiki Entity
title: UnderstandingResponse
id: class:parrot.handlers.models.understanding.UnderstandingResponse
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Serialised subset of AIMessage returned to callers.
---

# UnderstandingResponse

Defined in [`parrot.handlers.models.understanding`](../summaries/mod:parrot.handlers.models.understanding.md).

```python
class UnderstandingResponse(BaseModel)
```

Serialised subset of AIMessage returned to callers.

Only the fields relevant to the understanding endpoint are exposed here;
this keeps the response payload compact and stable.

## Methods

- `def from_ai_message(cls, msg: Any) -> 'UnderstandingResponse'` — Build an UnderstandingResponse from an AIMessage instance.
