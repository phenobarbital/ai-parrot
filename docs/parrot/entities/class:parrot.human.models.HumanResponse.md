---
type: Wiki Entity
title: HumanResponse
id: class:parrot.human.models.HumanResponse
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Response from a human to an interaction.
---

# HumanResponse

Defined in [`parrot.human.models`](../summaries/mod:parrot.human.models.md).

```python
class HumanResponse(BaseModel)
```

Response from a human to an interaction.

Note:
    ``response_type`` reuses :class:`InteractionType` to describe the
    *format* the channel actually delivered (e.g. Telegram may deliver
    a FORM as FREE_TEXT). The compatibility map lives in
    ``HumanInteractionManager._COMPATIBLE_TYPES``.
