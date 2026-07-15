---
type: Wiki Entity
title: SemanticUIResult
id: class:parrot.integrations.msagentsdk.semantic.SemanticUIResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Card-oriented semantic description of an agent result.
---

# SemanticUIResult

Defined in [`parrot.integrations.msagentsdk.semantic`](../summaries/mod:parrot.integrations.msagentsdk.semantic.md).

```python
class SemanticUIResult(BaseModel)
```

Card-oriented semantic description of an agent result.

Domain agents/tools construct this model and return it as explicit
structured output (via ``ask(structured_output=SemanticUIResult)`` or by
setting it on the response) to opt in to rich Adaptive Card rendering in
the ``msagentsdk`` bridge. The adapter never infers this model from free
text.

Attributes:
    title: The card's title.
    summary: Optional short summary text shown below the title.
    payload: The result payload, discriminated by ``result_type`` into
        one of :class:`TablePayload`, :class:`MetricsPayload`,
        :class:`DetailPayload`, :class:`StatusPayload`.
    actions: Card action buttons rendered below the payload.
