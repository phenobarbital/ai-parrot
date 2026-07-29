---
type: Concept
title: qualified_table()
id: func:parrot_formdesigner.services._identifiers.qualified_table
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return ``"<schema>"."<table>"`` after validating both identifiers.
---

# qualified_table

```python
def qualified_table(schema: str, table: str) -> str
```

Return ``"<schema>"."<table>"`` after validating both identifiers.

Args:
    schema: Postgres schema name.
    table: Table name within that schema.

Returns:
    A double-quoted, dot-qualified table reference safe to interpolate.
