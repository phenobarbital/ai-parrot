---
type: Wiki Entity
title: RelayPageInfo
id: class:parrot_tools.interfaces.gigsmart.models.common.RelayPageInfo
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: GraphQL Relay PageInfo fragment.
---

# RelayPageInfo

Defined in [`parrot_tools.interfaces.gigsmart.models.common`](../summaries/mod:parrot_tools.interfaces.gigsmart.models.common.md).

```python
class RelayPageInfo(BaseModel)
```

GraphQL Relay PageInfo fragment.

Args:
    has_next_page: True when more pages follow the current cursor.
    has_previous_page: True when pages precede the current cursor.
    start_cursor: Cursor for the first edge in the current page.
    end_cursor: Cursor for the last edge in the current page — pass as
        ``after`` to fetch the next page.
