---
type: Concept
title: get_source_class()
id: func:parrot.tools.databasequery.sources.get_source_class
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Look up a registered database source class by driver name.
---

# get_source_class

```python
def get_source_class(driver: str) -> type[AbstractDatabaseSource]
```

Look up a registered database source class by driver name.

Resolves aliases via ``normalize_driver()`` before lookup.
Lazily imports all source modules on first call.

Args:
    driver: Driver name or alias (e.g., ``'pg'``, ``'postgresql'``).

Returns:
    The registered ``AbstractDatabaseSource`` subclass.

Raises:
    ValueError: If no source is registered for the given driver.
