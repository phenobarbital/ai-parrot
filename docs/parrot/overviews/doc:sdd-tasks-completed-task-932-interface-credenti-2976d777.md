---
type: Wiki Overview
title: 'TASK-932: Expand interface credential resolution and update sources'
id: doc:sdd-tasks-completed-task-932-interface-credential-resolution-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec Module 2. `parrot.interfaces.database.get_default_credentials()` is
  a
relates_to:
- concept: mod:parrot.interfaces.database
  rel: mentions
---

# TASK-932: Expand interface credential resolution and update sources

**Feature**: FEAT-136 — database-toolkit-parity
**Spec**: `sdd/specs/database-toolkit-parity.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-931
**Assigned-to**: unassigned

---

## Context

Spec Module 2. `parrot.interfaces.database.get_default_credentials()` is a
PG-only stub that returns `None` for all other drivers. This means the toolkit
cannot connect to MySQL, BigQuery, MongoDB, etc. without explicit credentials
— a critical functional regression from the legacy `DatabaseQueryTool`.

This task expands the interface function to return `dict[str, Any]` for every
supported driver, then updates each source's `get_default_credentials()` to
delegate to it.

---

## Scope

**Step A — Expand the interface function:**

- Refactor `get_default_credentials()` in `parrot/interfaces/database.py`
  (line 490) from `Optional[str]` return to `dict[str, Any]`.
- Add per-driver credential dicts reading from `navconfig.config`, using the
  exact same env var names and fallbacks as `DatabaseQueryTool._get_default_credentials()`
  (tool.py:554-660) — this is the authoritative reference.
- Guard `querysource.conf` imports with `try/except ImportError`.
- Return `{}` when env vars are not set (never raise).
- Strip `None` values from the returned dict.

**Step B — Update each source's `get_default_credentials()` override:**

- Each source calls the expanded interface and applies driver-specific
  post-processing as needed:
  - `PostgresSource`: also include `dsn` from `querysource.conf.default_dsn`
  - `DocumentDBSource`: `setdefault("ssl", True)`, `setdefault("tlsCAFile", ...)`
  - `AtlasSource`: normalize DSN to `mongodb+srv://` scheme
  - All others: call interface, return as-is

- Write unit tests for the interface function and key source overrides.

**NOT in scope**: modifying toolkit.py, modifying tool.py, test_connection
overrides, or row-limit work.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/interfaces/database.py` | MODIFY | Expand `get_default_credentials()` to all drivers |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/postgres.py` | MODIFY | Delegate to interface + add param dict |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/mysql.py` | MODIFY | Delegate to interface |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/bigquery.py` | MODIFY | Delegate to interface |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/oracle.py` | MODIFY | Delegate to interface |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/mssql.py` | MODIFY | Delegate to interface |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/clickhouse.py` | MODIFY | Delegate to interface |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/influx.py` | MODIFY | Delegate to interface |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/mongodb.py` | MODIFY | Delegate to interface |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/atlas.py` | MODIFY | Delegate to interface + URI normalization |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/documentdb.py` | MODIFY | Delegate to interface + SSL defaults |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/elastic.py` | MODIFY | Delegate to interface |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/sqlite.py` | MODIFY | Delegate to interface |
| `packages/ai-parrot/src/parrot/tools/databasequery/sources/duckdb.py` | MODIFY | No change (in-memory default OK) |
| `tests/tools/test_database_credentials.py` | CREATE | Unit tests for interface + sources |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.interfaces.database import get_default_credentials  # verified: database.py:490
from navconfig import config                                     # verified: used by tool.py:15
from navconfig import BASE_DIR                                   # verified: used by tool.py:15
```

### Existing Signatures to Use
```python
# parrot/interfaces/database.py:490
def get_default_credentials(driver: str) -> Optional[str]:
    # CURRENT — will be changed to -> dict[str, Any]
    # Only supports _PG_ALIASES (line 487)

# navconfig.config — env var access pattern (from tool.py)
config.get('PG_HOST', fallback='localhost')
config.get('PG_PORT', fallback='5432')
# etc. for each driver

# querysource.conf — optional imports
from querysource.conf import default_dsn   # PG DSN
from querysource.conf import INFLUX_TOKEN  # InfluxDB token
```

### Reference: Legacy tool credential dict (tool.py:554-660)
```python
# This is the AUTHORITATIVE reference for env var names.
# The interface must use the exact same variable names.
'pg': {
    'host': config.get('PG_HOST', fallback='localhost'),
    'port': config.get('PG_PORT', fallback='5432'),
    'database': config.get('PG_DATABASE', fallback='postgres'),
    'user': config.get('PG_USER', fallback='postgres'),
    'password': config.get('PG_PWD') or config.get('PG_PASSWORD'),
}
'mysql': {
    'host': config.get('MYSQL_HOST', fallback='localhost'),
    'port': config.get('MYSQL_PORT', fallback='3306'),
    'database': config.get('MYSQL_DATABASE', fallback='mysql'),
    'user': config.get('MYSQL_USER', fallback='root'),
    'password': config.get('MYSQL_PASSWORD'),
}
'bigquery': {
    'credentials': Path(bigquery_creds_path).resolve() if bigquery_creds_path else None,
    'project_id': config.get('BIGQUERY_PROJECT_ID'),
}
'influx': {
    'host': config.get('INFLUX_HOST', fallback='localhost'),
    'port': config.get('INFLUX_PORT', fallback='8086'),
    'database': config.get('INFLUX_DATABASE', fallback='default'),
    'username': config.get('INFLUX_USERNAME'),
    'password': config.get('INFLUX_PASSWORD'),
    'token': INFLUX_TOKEN,
    'org': config.get('INFLUX_ORG', fallback='my-org'),
}
'oracle': {
    'host': config.get('ORACLE_HOST', fallback='localhost'),
    'port': config.get('ORACLE_PORT', fallback='1521'),
    'service_name': config.get('ORACLE_SERVICE_NAME', fallback='xe'),
    'user': config.get('ORACLE_USER'),
    'password': config.get('ORACLE_PASSWORD'),
}
'mssql': {
    'host': config.get('MSSQL_HOST', fallback='localhost'),
    'port': config.get('MSSQL_PORT', fallback='1433'),
    'database': config.get('MSSQL_DATABASE', fallback='master'),
    'user': config.get('MSSQL_USER'),
    'password': config.get('MSSQL_PASSWORD'),
}
'mongo': {
    'driver': 'mongo',
    'host': config.get('MONGODB_HOST', fallback='localhost'),
    'port': config.get('MONGODB_PORT', fallback='27017'),
    'database': config.get('MONGODB_DATABASE', fallback='test'),
    'username': config.get('MONGODB_USER'),
    'password': config.get('MONGODB_PASSWORD'),
    'dbtype': 'mongodb',
}
'atlas': {
    'driver': 'mongo',
    'host': config.get('ATLAS_HOST'),
    'port': config.get('ATLAS_PORT', fallback='27017'),
    'database': config.get('ATLAS_DATABASE', fallback='test'),
    'username': config.get('ATLAS_USER'),
    'password': config.get('ATLAS_PASSWORD'),
    'dbtype': 'atlas',
}
'documentdb': {
    'driver': 'mongo',
    'host': config.get('DOCUMENTDB_HOSTNAME', fallback='localhost'),
    'port': config.get('DOCUMENTDB_PORT', fallback='27017'),
    'database': config.get('DOCUMENTDB_DATABASE', fallback='test'),
    'username': config.get('DOCUMENTDB_USERNAME'),
    'password': config.get('DOCUMENTDB_PASSWORD'),
    'tlsCAFile': BASE_DIR.joinpath('env', "global-bundle.pem"),
    'ssl': config.get('DOCUMENTDB_USE_SSL', fallback=True),
    'collection_name': config.get('DOCUMENTDB_COLLECTION', fallback='mycollection'),
    'dbtype': 'documentdb',
}
'elastic': {
    'host': config.get('ELASTICSEARCH_HOST', fallback='localhost'),
    'port': config.get('ELASTICSEARCH_PORT', fallback='9200'),
    'db': config.get('ELASTICSEARCH_INDEX', fallback='logstash-*'),
    'user': config.get('ELASTICSEARCH_USER'),
    'password': config.get('ELASTICSEARCH_PASSWORD'),
    'protocol': config.get('ELASTICSEARCH_PROTOCOL', fallback='http'),
    'client_type': config.get('ELASTICSEARCH_CLIENT_TYPE', fallback='auto'),
}
'sqlite': {
    'database': config.get('SQLITE_DATABASE', fallback=':memory:'),
}
```

### Does NOT Exist
- ~~`parrot.interfaces.database.get_all_credentials()`~~ — not a function
- ~~`parrot.interfaces.database.CredentialStore`~~ — not a class
- ~~`AbstractDatabaseSource.credentials`~~ — not an attribute; credentials are passed per-call
- ~~`navconfig.config.get_dict()`~~ — not a method; use `config.get(key, fallback=...)`

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/interfaces/database.py — expanded function
def get_default_credentials(driver: str) -> dict[str, Any]:
    """Return default credentials for a database driver from env vars."""
    from navconfig import config
    driver_lower = driver.lower()
    # resolve aliases
    _ALIASES = {"postgres": "pg", "postgresql": "pg", "mariadb": "mysql", ...}
    canonical = _ALIASES.get(driver_lower, driver_lower)

    if canonical == "pg":
        # PG keeps DSN + param dict
        creds = {
            "host": config.get("PG_HOST", fallback="localhost"),
            ...
        }
        try:
            from querysource.conf import default_dsn
            creds["dsn"] = default_dsn
        except ImportError:
            pass
        return {k: v for k, v in creds.items() if v is not None}
    elif canonical == "mysql":
        ...
    # etc.
    return {}
```

### Key Constraints
- Return type changes from `Optional[str]` to `dict[str, Any]` — check all
  callers of the old function (`grep -rn "get_default_credentials"` in the
  whole project). The sources already handle dict returns.
- Use exact same env var names as tool.py (authoritative reference above)
- `querysource.conf` imports MUST be guarded with `try/except ImportError`
- Never raise on missing env vars — return `{}` or dict with fallback values
- Strip `None` values before returning

---

## Acceptance Criteria

- [ ] `get_default_credentials("pg")` returns dict with `host`, `port`, `database`, `user`, `password`, and `dsn` keys
- [ ] `get_default_credentials("mysql")` returns dict with `host`, `port`, `database`, `user`, `password`
- [ ] `get_default_credentials("bigquery")` returns dict with `credentials` path and `project_id`
- [ ] `get_default_credentials("mongo")` returns dict with `host`, `port`, `database`, `username`, `password`, `dbtype`
- [ ] `get_default_credentials("elastic")` returns dict with `host`, `port`, `db`, `user`, `password`, `protocol`, `client_type`
- [ ] `get_default_credentials("influx")` returns dict including `token` from querysource (when available)
- [ ] `get_default_credentials("documentdb")` returns dict including `ssl`, `tlsCAFile`, `dbtype`
- [ ] `get_default_credentials("unknowndriver")` returns `{}`
- [ ] `PostgresSource().get_default_credentials()` returns the interface dict + DSN
- [ ] `DocumentDBSource().get_default_credentials()` has `ssl=True` default
- [ ] `AtlasSource().get_default_credentials()` normalizes DSN to `mongodb+srv://`
- [ ] All tests pass: `pytest tests/tools/test_database_credentials.py -v`

---

## Test Specification

```python
import pytest
from unittest.mock import patch, MagicMock


class TestGetDefaultCredentials:
    def test_pg_returns_full_dict(self):
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("pg")
        assert isinstance(result, dict)
        # Should have fallback values even without env vars
        assert "host" in result or result == {}

    def test_mysql_returns_dict(self):
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("mysql")
        assert isinstance(result, dict)

    def test_unknown_driver_returns_empty(self):
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("nonexistent_driver")
        assert result == {}

    def test_aliases_resolve(self):
        from parrot.interfaces.database import get_default_credentials
        pg_result = get_default_credentials("postgresql")
        assert isinstance(pg_result, dict)

    def test_none_values_stripped(self):
        from parrot.interfaces.database import get_default_credentials
        result = get_default_credentials("pg")
        assert None not in result.values()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-931 is in `tasks/completed/`
3. **CRITICAL**: Before modifying the interface function, run
   `grep -rn "get_default_credentials" packages/` to find ALL callers and
   verify they can handle `dict` instead of `Optional[str]`
4. **Verify the Codebase Contract** — confirm all signatures still match
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** Step A (interface) first, then Step B (sources)
7. **Verify** all acceptance criteria are met
8. **Move this file** to `tasks/completed/TASK-932-interface-credential-resolution.md`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
