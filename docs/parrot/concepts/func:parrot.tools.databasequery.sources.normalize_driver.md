---
type: Concept
title: normalize_driver()
id: func:parrot.tools.databasequery.sources.normalize_driver
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Map driver aliases to their canonical names.
---

# normalize_driver

```python
def normalize_driver(driver: str) -> str
```

Map driver aliases to their canonical names.

This function is idempotent: passing a canonical driver name returns
the same name unchanged.

Args:
    driver: Driver name or alias (case-insensitive).

Returns:
    Canonical driver name.

Examples:
    >>> normalize_driver("postgresql")
    'pg'
    >>> normalize_driver("pg")
    'pg'
    >>> normalize_driver("opensearch")
    'elastic'
