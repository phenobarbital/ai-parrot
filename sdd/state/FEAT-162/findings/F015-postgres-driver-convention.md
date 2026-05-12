---
id: F015
query_id: Q015
type: grep
intent: Decide between asyncdb and asyncpg — search for which Postgres async driver pattern AI-Parrot already uses inside parrot/.
executed_at: 2026-05-12T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F015 — asyncdb is the dominant pattern (30 usages); raw asyncpg is rare (1 in parrot/, mostly used in comments)

## Summary

`asyncdb` (a Navigator-stack abstraction) is the dominant Postgres driver.
30 `from asyncdb` / `import asyncdb` matches across `parrot/` source. Only one
file uses raw `asyncpg`: `parrot/core/hooks/postgres.py` with
`asyncpg.connect(dsn=self._dsn)`. Most uses construct an `AsyncDB` or
`AsyncPool` with `driver="pg"` and a DSN. Several variants exist:
- `AsyncDB('pg', dsn=default_dsn)` — single-shot connection
- `AsyncPool(dsn=..., params=...)` — pool

**Resolution for OQ #1 (Postgres driver):** Use `asyncdb` to match the codebase.
The brainstorm's "lean toward asyncdb" is correct.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/database/toolkits/base.py`
  lines: 344-351
  symbol: AsyncPool / AsyncDB pattern
  excerpt: |
    from asyncdb import AsyncPool
    ...
    from asyncdb import AsyncDB
    self._connection = AsyncDB(driver, dsn=self.dsn, params=params)

- path: `packages/ai-parrot/src/parrot/bots/product.py`
  lines: 3, 120
  symbol: classic single-shot usage
  excerpt: |
    from asyncdb import AsyncDB
    ...
    db = AsyncDB('pg', dsn=_qs_conf.default_dsn)

- path: `packages/ai-parrot/src/parrot/handlers/bots.py`
  lines: 3-4, 130
  symbol: usage in handlers
  excerpt: |
    from asyncdb import AsyncDB  # asyncdb[default] is in core deps
    from asyncdb.exceptions import NoDataFound

- path: `packages/ai-parrot/src/parrot/core/hooks/postgres.py`
  lines: 43
  symbol: ONLY raw asyncpg usage in parrot/
  excerpt: |
    self._connection = await asyncpg.connect(dsn=self._dsn)

- path: `packages/ai-parrot/src/parrot/interfaces/database.py`
  lines: 12, 123
  symbol: AsyncDB-based DB interface
  excerpt: |
    from asyncdb import AsyncDB  # asyncdb[default] is in core deps
    ...
    return AsyncDB(driver, dsn=dsn, credentials=credentials)

## Notes

- For `PostgresS3SecurityReportStore`, follow the AsyncDB pattern. Reference
  `parrot/bots/database/toolkits/base.py` for connection/pool lifecycle and
  `parrot/interfaces/database.py` for credential-resolution conventions.
- AsyncDB's `'pg'` driver wraps asyncpg under the hood, so we still get async
  semantics without adding a new top-level dependency.
