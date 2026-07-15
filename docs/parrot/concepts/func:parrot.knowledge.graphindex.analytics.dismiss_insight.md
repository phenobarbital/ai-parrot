---
type: Concept
title: dismiss_insight()
id: func:parrot.knowledge.graphindex.analytics.dismiss_insight
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mark an insight as dismissed.
---

# dismiss_insight

```python
def dismiss_insight(analytics: AnalyticsResult, insight_id: str) -> None
```

Mark an insight as dismissed.

Creates a ``DismissedInsights`` container if one does not yet exist on
the analytics result, then adds ``insight_id`` to the dismissed set.

Insight IDs follow these conventions:
- Surprising connections: ``f"surprise:{conn['source_id']}:{conn['target_id']}"``
- Isolated nodes: ``f"isolated:{node['node_id']}"``
- Sparse communities: ``f"sparse:{community['community_id']}"``
- Bridge nodes: ``f"bridge:{node['node_id']}"``

Args:
    analytics: The ``AnalyticsResult`` to update in place.
    insight_id: The stable ID of the insight to dismiss.
