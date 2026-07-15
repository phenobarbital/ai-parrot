---
type: Wiki Entity
title: DatabaseResponse
id: class:parrot.bots.database.models.DatabaseResponse
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Component-based database response.
---

# DatabaseResponse

Defined in [`parrot.bots.database.models`](../summaries/mod:parrot.bots.database.models.md).

```python
class DatabaseResponse
```

Component-based database response.

## Methods

- `def to_markdown(self) -> str` — Convert response to markdown format.
- `def to_json(self) -> str` — Convert DatabaseResponse to JSON format.
- `def to_dict(self) -> Dict[str, Any]` — Convert to dictionary format for programmatic access.
- `def has_component(self, component: OutputComponent) -> bool` — Check if response includes a specific component.
- `def get_data_summary(self) -> Dict[str, Any]` — Get summary information about the data.
