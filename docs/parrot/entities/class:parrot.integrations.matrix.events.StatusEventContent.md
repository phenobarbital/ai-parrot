---
type: Wiki Entity
title: StatusEventContent
id: class:parrot.integrations.matrix.events.StatusEventContent
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Content of m.parrot.status message event.
---

# StatusEventContent

Defined in [`parrot.integrations.matrix.events`](../summaries/mod:parrot.integrations.matrix.events.md).

```python
class StatusEventContent(BaseModel)
```

Content of m.parrot.status message event.

Progress updates for in-flight tasks.
Maps to TaskState.WORKING / FAILED / INPUT_REQUIRED.
