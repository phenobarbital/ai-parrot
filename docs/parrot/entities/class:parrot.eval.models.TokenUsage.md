---
type: Wiki Entity
title: TokenUsage
id: class:parrot.eval.models.TokenUsage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Aggregated token counts for a trajectory attempt.
---

# TokenUsage

Defined in [`parrot.eval.models`](../summaries/mod:parrot.eval.models.md).

```python
class TokenUsage(BaseModel)
```

Aggregated token counts for a trajectory attempt.

Attributes:
    prompt: Total prompt/input tokens consumed.
    completion: Total completion/output tokens consumed.
    total: Sum of prompt and completion tokens.
