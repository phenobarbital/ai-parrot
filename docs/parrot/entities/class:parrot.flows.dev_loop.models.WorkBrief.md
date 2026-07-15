---
type: Wiki Entity
title: WorkBrief
id: class:parrot.flows.dev_loop.models.WorkBrief
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: User-facing input contract for the dev-loop flow.
---

# WorkBrief

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class WorkBrief(BaseModel)
```

User-facing input contract for the dev-loop flow.

Renamed from ``BugBrief`` in FEAT-132. The legacy name is preserved as
a module-level alias (``BugBrief = WorkBrief``) so existing
``from parrot.flows.dev_loop import BugBrief`` callers keep working
without edits.

Field declaration order is intentional: ``kind`` is first so the JSON
schema rendered by the dispatcher's ``_build_prompt`` surfaces it at
the top of the field list.
