---
type: Concept
title: register_source()
id: func:parrot.tools.databasequery.sources.register_source
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Decorator that registers a database source class in the registry.
---

# register_source

```python
def register_source(driver: str) -> Callable[[type], type]
```

Decorator that registers a database source class in the registry.

The ``driver`` parameter should be the **canonical** driver name
(e.g., ``'pg'``, not ``'postgres'``). Aliases are resolved via
``normalize_driver()`` before lookup.

Args:
    driver: Canonical driver name to register the source under.

Returns:
    Class decorator that registers the source and returns the class unchanged.

Example:
    >>> @register_source("pg")
    ... class PostgresSource(AbstractDatabaseSource):
    ...     driver = "pg"
