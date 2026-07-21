---
type: Wiki Entity
title: DatabaseQueryArgs
id: class:parrot.tools.databasequery.tool.DatabaseQueryArgs
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Arguments schema for DatabaseQueryTool.
---

# DatabaseQueryArgs

Defined in [`parrot.tools.databasequery.tool`](../summaries/mod:parrot.tools.databasequery.tool.md).

```python
class DatabaseQueryArgs(BaseModel)
```

Arguments schema for DatabaseQueryTool.

## Methods

- `def validate_timeout(cls, v)`
- `def validate_max_rows(cls, v)`
- `def validate_driver(cls, v)`
- `def validate_credentials(cls, v)` — Ensure credentials is either None, a dict, or a DSN string.
