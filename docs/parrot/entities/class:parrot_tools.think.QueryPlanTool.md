---
type: Wiki Entity
title: QueryPlanTool
id: class:parrot_tools.think.QueryPlanTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Specialized thinking tool for database query planning.
relates_to:
- concept: class:parrot_tools.think.ThinkTool
  rel: extends
---

# QueryPlanTool

Defined in [`parrot_tools.think`](../summaries/mod:parrot_tools.think.md).

```python
class QueryPlanTool(ThinkTool)
```

Specialized thinking tool for database query planning.

Guides the agent to consider query optimization, table relationships,
and potential performance issues.

Example:
    >>> tool = QueryPlanTool()
    >>> result = await tool.execute(
    ...     thoughts="Need to join orders with customers and products. "
    ...              "Orders table is large (~5M rows), should filter by "
    ...              "date range first. Index exists on order_date."
    ... )
