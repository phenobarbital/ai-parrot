---
type: Concept
title: driver_to_dialect()
id: func:parrot.tools.dataset_manager.sources.dialects.driver_to_dialect
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Map an ai-parrot driver name to a sqlglot dialect identifier.
---

# driver_to_dialect

```python
def driver_to_dialect(driver: str) -> Optional[str]
```

Map an ai-parrot driver name to a sqlglot dialect identifier.

Normalises the driver name via :func:`normalize_driver` before lookup so
that raw aliases (``"postgres"``, ``"bq"``, ``"sqlserver"``, …) are
resolved the same way as canonical names.

Args:
    driver: Raw or pre-normalised ai-parrot driver name.

Returns:
    A sqlglot dialect string (e.g. ``"postgres"``, ``"bigquery"``), or
    ``None`` if the driver is not in the known map.  The caller is
    responsible for deciding whether an unmapped driver is fail-open or
    fail-closed.

Examples::

    >>> driver_to_dialect("pg")
    'postgres'
    >>> driver_to_dialect("bq")
    'bigquery'
    >>> driver_to_dialect("mssql")
    'tsql'
    >>> driver_to_dialect("unknown_db_xyz") is None
    True
