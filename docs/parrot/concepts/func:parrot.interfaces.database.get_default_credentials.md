---
type: Concept
title: get_default_credentials()
id: func:parrot.interfaces.database.get_default_credentials
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return default credentials for a database driver from environment variables.
---

# get_default_credentials

```python
def get_default_credentials(driver: str) -> dict[str, Any]
```

Return default credentials for a database driver from environment variables.

Reads from ``navconfig.config`` using the same environment variable names
as the legacy ``DatabaseQueryTool._get_default_credentials()`` (the
authoritative reference). Returns ``{}`` when no env vars are set.
Guards ``querysource.conf`` imports with ``try/except ImportError``.

This is the single source of truth for env-var-based credential resolution
across the toolkit layer (``AbstractDatabaseSource.get_default_credentials``)
and the legacy tool layer (``DatabaseQueryTool._get_default_credentials``).

Args:
    driver: Database driver name or alias
        (e.g. ``'pg'``, ``'postgresql'``, ``'mysql'``, ``'elastic'``).

Returns:
    A ``dict[str, Any]`` with driver-specific credential keys. Returns
    ``{}`` if the driver is unknown or no environment variables are set.
    ``None`` values are stripped from the returned dict.

Examples:
    >>> get_default_credentials("pg")
    {'host': 'localhost', 'port': '5432', 'database': 'postgres', ...}
    >>> get_default_credentials("unknowndriver")
    {}
