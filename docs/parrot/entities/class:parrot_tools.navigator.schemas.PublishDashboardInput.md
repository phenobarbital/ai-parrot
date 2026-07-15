---
type: Wiki Entity
title: PublishDashboardInput
id: class:parrot_tools.navigator.schemas.PublishDashboardInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input for publishing a draft dashboard (promote to system-wide).
---

# PublishDashboardInput

Defined in [`parrot_tools.navigator.schemas`](../summaries/mod:parrot_tools.navigator.schemas.md).

```python
class PublishDashboardInput(BaseModel)
```

Input for publishing a draft dashboard (promote to system-wide).

Transitions a personal/draft dashboard (``is_system=False`` with a
specific ``user_id`` owner) into a published/system one
(``is_system=True`` with ``user_id=NULL``).
