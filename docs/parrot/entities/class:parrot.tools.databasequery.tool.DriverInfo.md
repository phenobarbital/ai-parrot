---
type: Wiki Entity
title: DriverInfo
id: class:parrot.tools.databasequery.tool.DriverInfo
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Driver metadata wrapper preserved for back-compat (FEAT-105).
---

# DriverInfo

Defined in [`parrot.tools.databasequery.tool`](../summaries/mod:parrot.tools.databasequery.tool.md).

```python
class DriverInfo
```

Driver metadata wrapper preserved for back-compat (FEAT-105).

Pre-FEAT-105, this class lived in ``parrot_tools.databasequery`` and exposed
classmethods used by external plugins. The migration moved its internals to
module-level helpers (``_DRIVER_TO_QUERY_LANGUAGE``, ``_get_query_language``,
``normalize_driver``). This thin wrapper restores the legacy surface so the
``parrot_tools.databasequery`` shim keeps working.

## Methods

- `def normalize_driver(cls, driver: str) -> str` — Normalize a driver alias to its canonical name.
- `def get_query_language(cls, driver: str) -> QueryLanguage` — Return the QueryLanguage for a driver alias or canonical name.
