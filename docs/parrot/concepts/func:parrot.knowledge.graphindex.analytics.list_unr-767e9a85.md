---
type: Concept
title: list_unreviewed_insights()
id: func:parrot.knowledge.graphindex.analytics.list_unreviewed_insights
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return all insights not yet dismissed.
---

# list_unreviewed_insights

```python
def list_unreviewed_insights(analytics: AnalyticsResult) -> list[dict]
```

Return all insights not yet dismissed.

Aggregates surprising connections and knowledge gap entries (isolated
nodes, sparse communities, bridge nodes) into a flat list, assigns
each a stable ``id`` field, and filters out any IDs in
``analytics.dismissed.dismissed_ids``.

Args:
    analytics: The ``AnalyticsResult`` to inspect.

Returns:
    List of insight dicts, each containing at minimum an ``id`` field
    (the stable insight ID) and the original insight data. The list
    is NOT sorted.
