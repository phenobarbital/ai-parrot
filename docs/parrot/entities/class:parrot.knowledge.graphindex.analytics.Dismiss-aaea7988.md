---
type: Wiki Entity
title: DismissedInsights
id: class:parrot.knowledge.graphindex.analytics.DismissedInsights
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tracks dismissed insight IDs. Session-scoped (not persisted to DB).
---

# DismissedInsights

Defined in [`parrot.knowledge.graphindex.analytics`](../summaries/mod:parrot.knowledge.graphindex.analytics.md).

```python
class DismissedInsights(BaseModel)
```

Tracks dismissed insight IDs. Session-scoped (not persisted to DB).

Args:
    dismissed_ids: Set of insight IDs that have been marked as reviewed/dismissed.

## Methods

- `def serialize_dismissed_ids(self, v: set[str]) -> list[str]` — Serialize dismissed_ids as a sorted list for JSON compatibility.
