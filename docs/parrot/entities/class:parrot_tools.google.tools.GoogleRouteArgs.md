---
type: Wiki Entity
title: GoogleRouteArgs
id: class:parrot_tools.google.tools.GoogleRouteArgs
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Arguments schema for Google Route Search.
---

# GoogleRouteArgs

Defined in [`parrot_tools.google.tools`](../summaries/mod:parrot_tools.google.tools.md).

```python
class GoogleRouteArgs(BaseModel)
```

Arguments schema for Google Route Search.

## Methods

- `def validate_map_size(cls, v)` — Validate map_size format.
- `def map_width(self) -> int` — Get map width from map_size string.
- `def map_height(self) -> int` — Get map height from map_size string.
- `def get_map_size_tuple(self) -> tuple` — Get map_size as tuple.
- `def get_map_size_list(self) -> List[int]` — Get map_size as list.
