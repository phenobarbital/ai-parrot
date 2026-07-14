---
type: Wiki Entity
title: DetailPayload
id: class:parrot.integrations.msagentsdk.semantic.DetailPayload
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: An entity-detail result payload.
---

# DetailPayload

Defined in [`parrot.integrations.msagentsdk.semantic`](../summaries/mod:parrot.integrations.msagentsdk.semantic.md).

```python
class DetailPayload(BaseModel)
```

An entity-detail result payload.

Attributes:
    result_type: Discriminator, always ``"detail"``.
    fields: The labeled fields describing the entity.
