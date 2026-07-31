---
type: Wiki Overview
title: 'TASK-1016: PostgresResultStorage backend'
id: doc:sdd-tasks-completed-task-1016-postgres-result-storage-backend-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements the Postgres backend for FEAT-147. Uses `asyncdb.AsyncDB('pg')`
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.backends.postgres
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
---

# TASK-1016: PostgresResultStorage backend

**Feature**: FEAT-147 — Crew Result Storage Backends
**Spec**: `sdd/specs/crew-result-storage-backends.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1013
**Assigned-to**: unassigned

---

## Context

Implements the Postgres backend for FEAT-147. Uses `asyncdb.AsyncDB('pg')`
(asyncpg under the hood) to write each crew/flow execution as one row in
a `jsonb`-payload table. DDL is idempotent and runs once per process per
table. Resolves spec §2 "Backend: Postgres" and §3 Module 4.

This task is conceptually parallel to TASK-1014 and TASK-1015 — they
share no source files.

---

## Scope

- Implement `PostgresResultStorage(ResultStorage)` in
  `parrot/bots/flows/core/storage/backends/postgres.py`.
- Use `asyncdb.AsyncDB('pg', dsn=...)` mirroring
  `parrot/interfaces/hierarchy.py:86` and `parrot/bots/product.py:118`.
- DSN source: constructor argument, then
  `parrot.conf.CREW_RESULT_STORAGE_PG_DSN`, then `parrot.conf.default_dsn`.
- Connection lifecycle: lazy-connect on first `save()`, store the
  connection on `self._conn`; `close()` releases it.
- Idempotent DDL on first write per table (`crew_executions`,
  `flow_executions`). Cache of already-initialised tables on
  `self._initialised: set[str]`.
- Insert via parameterised query into the named columns
  (`crew_name`, `method`, `user_id`, `session_id`, `timestamp`,
  `payload`). Anything outside those columns is merged into `payload`.
- `result.to_dict()` may be missing — when the document's `result` field
  is a bare string, wrap it as `{"raw": <str>}` before encoding into
  `payload` (per spec §7 gotcha).
- Failures inside `save()` log a WARNING and are swallowed.
- Add unit tests with a mocked `AsyncDB` recording the queries.

**NOT in scope**: Any schema-migration system, indexes beyond the two
declared in the spec, cleanup of the table contents, partitioning, or
range-based retention. Reading past executions.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/flows/core/storage/backends/postgres.py` | CREATE | `PostgresResultStorage`. |
| `tests/bots/flows/core/storage/test_postgres_backend.py` | CREATE | Unit tests with mocked asyncdb. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from asyncdb import AsyncDB                               # verified: parrot/handlers/agents/abstract.py:13, parrot/interfaces/hierarchy.py:8
from parrot.conf import CREW_RESULT_STORAGE_PG_DSN        # CREATED by TASK-1013
```

### Existing Signatures to Use
```python
# parrot/interfaces/hierarchy.py:86
self.pg_client = AsyncDB('pg', dsn=default_dsn)

# parrot/bots/product.py:118
db = AsyncDB('pg', dsn=_qs_conf.default_dsn)
```

The asyncdb `pg` driver provides:
- `await conn.connection()` — open the underlying asyncpg pool/connection.
- `await conn.execute(query, *params)` — run a statement (DDL or
  parameterised insert with `$1`, `$2`, ... placeholders).
- `await conn.close()` — release.

### DDL (verbatim, must remain idempotent)
```sql
CREATE TABLE IF NOT EXISTS {table} (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  crew_name   text        NOT NULL,
  method      text        NOT NULL,
  user_id     text,
  session_id  text,
  timestamp   timestamptz NOT NULL DEFAULT now(),
  payload     jsonb       NOT NULL
);
CREATE INDEX IF NOT EXISTS {table}_crew_name_idx ON {table} (crew_name);
CREATE INDEX IF NOT EXISTS {table}_session_id_idx ON {table} (session_id);
```

`{table}` is whitelisted to a small set (`crew_executions`,
`flow_executions`) and validated against `^[a-z_][a-z0-9_]*$` before
substitution to prevent injection — never f-string user input directly
into DDL without that check.

### Does NOT Exist
- ~~`asyncdb.PgStorage`~~ — no such class. Always go through `AsyncDB('pg', dsn=...)`.
- ~~`AsyncDB.write_pg`~~ — not a method.
- ~~A central `crew_executions` migration in any `alembic/` directory~~ — there is no alembic in this repo. The DDL must be issued by the backend.

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/bots/flows/core/storage/backends/postgres.py
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from navconfig.logging import logging
from asyncdb import AsyncDB

from parrot.conf import CREW_RESULT_STORAGE_PG_DSN
from .base import ResultStorage


_TABLE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_NAMED_COLUMNS = ("crew_name", "method", "user_id", "session_id", "timestamp")


class PostgresResultStorage(ResultStorage):
    """Persist crew/flow execution results to Postgres (one row per execution, jsonb payload)."""

    def __init__(self, dsn: Optional[str] = None) -> None:
        self._dsn = dsn or CREW_RESULT_STORAGE_PG_DSN
        self._conn = None
        self._initialised: set[str] = set()
        self.logger = logging.getLogger("parrot.crew_storage.postgres")

    async def _ensure(self):
        if self._conn is None:
            self._conn = AsyncDB("pg", dsn=self._dsn)
            await self._conn.connection()
        return self._conn

    async def _ensure_table(self, conn, table: str) -> None:
        if table in self._initialised:
            return
        if not _TABLE_RE.match(table):
            raise ValueError(f"Refusing to issue DDL for unsafe table name: {table!r}")
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {table} (
          id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
          crew_name   text        NOT NULL,
          method      text        NOT NULL,
          user_id     text,
          session_id  text,
          timestamp   timestamptz NOT NULL DEFAULT now(),
          payload     jsonb       NOT NULL
        );
        CREATE INDEX IF NOT EXISTS {table}_crew_name_idx ON {table} (crew_name);
        CREATE INDEX IF NOT EXISTS {table}_session_id_idx ON {table} (session_id);
        """
        await conn.execute(ddl)
        self._initialised.add(table)

    async def save(self, collection: str, document: dict[str, Any]) -> None:
        try:
            conn = await self._ensure()
            await self._ensure_table(conn, collection)

            crew_name  = document.get("crew_name", "unknown")
            method     = document.get("method", "unknown")
            user_id    = document.get("user_id")
            session_id = document.get("session_id")
            ts_raw     = document.get("timestamp")
            timestamp  = (
                datetime.fromtimestamp(ts_raw, tz=timezone.utc)
                if isinstance(ts_raw, (int, float))
                else datetime.now(tz=timezone.utc)
            )

            payload_dict = {
                k: v for k, v in document.items()
                if k not in _NAMED_COLUMNS
            }
            # Spec §7 gotcha: bare-string `result` must be wrapped as {"raw": ...}
            if isinstance(payload_dict.get("result"), str):
                payload_dict["result"] = {"raw": payload_dict["result"]}
            payload = json.dumps(payload_dict, default=str)

            await conn.execute(
                f"INSERT INTO {collection} "
                f"(crew_name, method, user_id, session_id, timestamp, payload) "
                f"VALUES ($1, $2, $3, $4, $5, $6)",
                crew_name, method, user_id, session_id, timestamp, payload,
            )
        except Exception as exc:
            self.logger.warning(
                "PostgresResultStorage save failed for collection=%s: %s",
                collection, exc,
            )

    async def close(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.close()
            finally:
                self._conn = None
                self._initialised.clear()
```

### Key Constraints
- DDL must run once per `(process, table)` pair — use the `_initialised`
  set. Subsequent `save()` calls for the same table skip the DDL.
- Never interpolate user-controlled strings into the SQL template. The
  table name comes from internal callers (`crew_executions`,
  `flow_executions`) and is validated by the regex; values go through
  `$1`–`$6` placeholders.
- All exceptions inside `save()` are swallowed (preserves
  fire-and-forget contract).

### References in Codebase
- `parrot/interfaces/hierarchy.py:86` — asyncdb pg init pattern.
- `parrot/bots/product.py:118` — asyncdb pg init pattern.

---

## Acceptance Criteria

- [ ] `from parrot.bots.flows.core.storage.backends import PostgresResultStorage` succeeds.
- [ ] `get_result_storage("postgres")` returns a `PostgresResultStorage` instance.
- [ ] First `save()` for `crew_executions` issues exactly one DDL block + one INSERT; second `save()` for the same table issues only INSERT (DDL cache hit).
- [ ] `save()` for a different table (`flow_executions`) issues a fresh DDL block.
- [ ] An invalid table name (e.g., `"crew_executions; DROP TABLE x;"`) is REJECTED with `ValueError` before any SQL is issued.
- [ ] When `document["result"]` is a bare string, the persisted `payload` jsonb wraps it as `{"raw": "..."}`.
- [ ] Backend `save()` failures (driver raises) are logged at WARNING and do not propagate.
- [ ] `close()` releases the connection and is idempotent.
- [ ] `pytest tests/bots/flows/core/storage/test_postgres_backend.py -v` is green.
- [ ] `ruff check parrot/bots/flows/core/storage/backends/postgres.py` is clean.

---

## Test Specification

```python
# tests/bots/flows/core/storage/test_postgres_backend.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_asyncdb(monkeypatch):
    conn = MagicMock()
    conn.connection = AsyncMock(return_value=conn)
    conn.execute = AsyncMock(return_value=None)
    conn.close = AsyncMock(return_value=None)
    cls = MagicMock(return_value=conn)
    monkeypatch.setattr(
        "parrot.bots.flows.core.storage.backends.postgres.AsyncDB",
        cls,
    )
    return conn


@pytest.mark.asyncio
async def test_postgres_first_save_issues_ddl_and_insert(mock_asyncdb):
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage
    backend = PostgresResultStorage(dsn="postgres://x/y")
    await backend.save("crew_executions", {"crew_name": "x", "method": "run_flow"})
    calls = [c.args[0] for c in mock_asyncdb.execute.await_args_list]
    assert any("CREATE TABLE IF NOT EXISTS crew_executions" in q for q in calls)
    assert any("INSERT INTO crew_executions" in q for q in calls)


@pytest.mark.asyncio
async def test_postgres_second_save_skips_ddl(mock_asyncdb):
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage
    backend = PostgresResultStorage(dsn="postgres://x/y")
    await backend.save("crew_executions", {"crew_name": "x", "method": "m"})
    mock_asyncdb.execute.reset_mock()
    await backend.save("crew_executions", {"crew_name": "y", "method": "m"})
    calls = [c.args[0] for c in mock_asyncdb.execute.await_args_list]
    assert all("CREATE TABLE" not in q for q in calls)
    assert any("INSERT INTO crew_executions" in q for q in calls)


@pytest.mark.asyncio
async def test_postgres_rejects_unsafe_table_name(mock_asyncdb):
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage
    backend = PostgresResultStorage(dsn="postgres://x/y")
    # Should be swallowed by the outer try/except and logged — no SQL issued.
    await backend.save("crew_executions; DROP TABLE x;", {"crew_name": "x"})
    calls = [c.args[0] for c in mock_asyncdb.execute.await_args_list]
    assert all("DROP TABLE" not in q for q in calls)


@pytest.mark.asyncio
async def test_postgres_wraps_bare_string_result(mock_asyncdb):
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage
    backend = PostgresResultStorage(dsn="postgres://x/y")
    await backend.save(
        "crew_executions",
        {"crew_name": "x", "method": "m", "result": "raw-string"},
    )
    insert_call = next(
        c for c in mock_asyncdb.execute.await_args_list
        if "INSERT INTO" in c.args[0]
    )
    payload_arg = insert_call.args[6]
    payload = json.loads(payload_arg)
    assert payload["result"] == {"raw": "raw-string"}


@pytest.mark.asyncio
async def test_postgres_close_idempotent(mock_asyncdb):
    from parrot.bots.flows.core.storage.backends import PostgresResultStorage
    backend = PostgresResultStorage(dsn="postgres://x/y")
    await backend.close()
    await backend.save("crew_executions", {"crew_name": "x", "method": "m"})
    await backend.close()
    await backend.close()
```

---

## Agent Instructions

1. **Read the spec** §2 "Backend: Postgres" and verify TASK-1013 is in `tasks/completed/`.
2. **Activate the venv**: `source .venv/bin/activate`.
3. **Verify** the asyncdb pg API by skimming `parrot/interfaces/hierarchy.py:86` and `parrot/bots/product.py:118`.
4. **Implement** the backend.
5. **Run** `pytest tests/bots/flows/core/storage/test_postgres_backend.py -v`.
6. **Move this file** to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-05
**Notes**: 7 tests pass. Idempotent DDL with table regex validation,
bare-string result wrapping, jsonb payload, lazy connection,
idempotent close.

**Deviations from spec**: none
