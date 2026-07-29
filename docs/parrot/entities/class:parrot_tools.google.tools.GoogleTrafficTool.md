---
type: Wiki Entity
title: GoogleTrafficTool
id: class:parrot_tools.google.tools.GoogleTrafficTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Retrieve Google popular times data to estimate venue traffic.
relates_to:
- concept: class:parrot_tools.google.tools.GooglePlacesBaseTool
  rel: extends
---

# GoogleTrafficTool

Defined in [`parrot_tools.google.tools`](../summaries/mod:parrot_tools.google.tools.md).

```python
class GoogleTrafficTool(GooglePlacesBaseTool)
```

Retrieve Google popular times data to estimate venue traffic.

## Methods

- `def convert_populartimes(self, popular_times: Dict[str, Dict[str, Dict[str, Any]]]) -> Dict[str, Dict[str, Dict[str, Any]]]`
- `def index_get(array: Any, *argv: int) -> Optional[Any]`
