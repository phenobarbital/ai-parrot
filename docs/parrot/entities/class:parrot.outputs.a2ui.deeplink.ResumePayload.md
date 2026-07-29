---
type: Wiki Entity
title: ResumePayload
id: class:parrot.outputs.a2ui.deeplink.ResumePayload
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Server-side payload restored when a deep link is consumed.
---

# ResumePayload

Defined in [`parrot.outputs.a2ui.deeplink`](../summaries/mod:parrot.outputs.a2ui.deeplink.md).

```python
class ResumePayload(BaseModel)
```

Server-side payload restored when a deep link is consumed.

Never serialized into the token URL — it lives only in Redis (spec §7).
