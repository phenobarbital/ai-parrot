---
type: Wiki Entity
title: StatusPayload
id: class:parrot.integrations.msagentsdk.semantic.StatusPayload
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A status/error result payload.
---

# StatusPayload

Defined in [`parrot.integrations.msagentsdk.semantic`](../summaries/mod:parrot.integrations.msagentsdk.semantic.md).

```python
class StatusPayload(BaseModel)
```

A status/error result payload.

Attributes:
    result_type: Discriminator, always ``"status"``.
    level: The severity level of the status.
    message: The primary status message.
    details: Optional additional details/context.
