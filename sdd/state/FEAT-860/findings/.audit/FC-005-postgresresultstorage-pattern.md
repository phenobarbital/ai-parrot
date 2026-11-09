---
id: FC-005
query_id: Q010
type: read
intent: "Read PostgresResultStorage: pool/DSN acquisition, _ensure_table DDL, jsonb payload, tenant column."
executed_at: 2026-11-09T17:21:30Z
duration_ms: 700
parent_id: null
depth: 0
---

# FC-005 — PostgresResultStorage: asyncdb single connection from CREW_RESULT_STORAGE_PG_DSN, lazy idempotent DDL, jsonb payload, unqualified table names only

## Summary

`PostgresResultStorage(ResultStorage)` (core, `bots/flows/core/storage/backends/postgres.py`, 438 lines)
opens ONE lazy `asyncdb.AsyncDB("pg", dsn=...)` connection on first use (`_ensure`), DSN defaulting to
`parrot.conf.CREW_RESULT_STORAGE_PG_DSN`. On first use per table it runs idempotent DDL
(`CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS`),
cached per process in `self._initialised`. Table names are f-string-interpolated after validation
against `^[a-z_][a-z0-9_]*$` — a schema-qualified name such as `navigator.crew_definitions` would be
REJECTED by this regex. Writes are plain `INSERT ... VALUES ($1..$9)` with `json.dumps(payload, default=str)`
into a `jsonb` column; `save()` swallows errors (warning), `fetch()` re-raises. `close()` is idempotent.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py`
  lines: 12-25
  symbol: `imports / _TABLE_RE / _NAMED_COLUMNS`
  excerpt: |
    from asyncdb import AsyncDB
    from parrot.conf import CREW_RESULT_STORAGE_PG_DSN
    from .base import ResultStorage
    _TABLE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

- path: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py`
  lines: 40-56
  symbol: `PostgresResultStorage.__init__ / _ensure`
  excerpt: |
    def __init__(self, dsn: Optional[str] = None) -> None:
        self._dsn = dsn or CREW_RESULT_STORAGE_PG_DSN
        self._conn: Optional[AsyncDB] = None
        self._initialised: set[str] = set()
    async def _ensure(self) -> AsyncDB:
        if self._conn is None:
            self._conn = AsyncDB("pg", dsn=self._dsn)
            await self._conn.connection()

- path: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py`
  lines: 58-110
  symbol: `PostgresResultStorage._ensure_table`
  excerpt: |
    if not _TABLE_RE.match(table): raise ValueError(...)
    if table in self._initialised: return
    await conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ("
        f"  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), crew_name text NOT NULL, ..."
        f"  timestamp timestamptz NOT NULL DEFAULT now(), payload jsonb NOT NULL)")
    await conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant TEXT NOT NULL DEFAULT 'global'")
    await conn.execute(f"CREATE INDEX IF NOT EXISTS {table}_tenant_user_idx ON {table} (tenant, user_id)")
    self._initialised.add(table)

- path: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py`
  lines: 112-162
  symbol: `PostgresResultStorage.save`
  excerpt: |
    payload = json.dumps(payload_dict, default=str)
    await conn.execute(f"INSERT INTO {collection} "
        "(crew_name, method, user_id, session_id, execution_id, timestamp, tenant, prompt, payload) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)", ...)
    except Exception as exc: self.logger.warning(...)   # swallowed

- path: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py`
  lines: 164-217
  symbol: `PostgresResultStorage.fetch / close`
  excerpt: |
    rows = await conn.execute(f"SELECT ... payload FROM {collection} WHERE execution_id = $1", execution_id)
    payload = row_dict.pop("payload", {}) or {}
    if isinstance(payload, str): payload = json.loads(payload)
    ...
    async def close(self) -> None:  # idempotent; clears _initialised

- path: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py`
  lines: 223-230
  symbol: `PostgresResultStorage._build_where`
  excerpt: |
    Legacy rows with ``tenant IS NULL`` are matched via
    ``COALESCE(tenant, 'global')`` so pre-FEAT-307 records remain visible
    under the ``"global"`` tenant.

## Notes

- Reusable pattern for a crew-definition store: asyncdb `AsyncDB("pg", dsn=...)`, `$n` placeholders,
  idempotent DDL, `jsonb` payload, `tenant TEXT NOT NULL DEFAULT 'global'`, read errors re-raised.
- Not reusable as-is: the regex forbids `schema.table`; a `navigator.crew_definitions` store must quote/
  validate schema and table separately.
- No UPSERT exists here (executions are append-only); a definitions store needs
  `INSERT ... ON CONFLICT (tenant, name) DO UPDATE` (no precedent in this file).
- A jsonb value returned by asyncdb may come back as `str` (handled by `json.loads` at 197-198).
- Single connection, no pool: concurrent coroutines share one connection (acceptable for low-rate
  definition CRUD; a startup bulk load is sequential anyway).
