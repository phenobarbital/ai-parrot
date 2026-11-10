---
id: FW-010
query_id: Q005
type: wiki_page
intent: "Read PostgresResultStorage internals: connection, DDL, jsonb payload, tenant column."
executed_at: 2026-11-09T17:13:17Z
duration_ms: 400
parent_id: FW-009
depth: 1
---

# FW-010 — PostgresResultStorage: asyncdb AsyncDB("pg") from a dedicated DSN, lazy connect, in-process idempotent DDL, jsonb payload

## Summary

`PostgresResultStorage(dsn=None)` falls back to `parrot.conf.CREW_RESULT_STORAGE_PG_DSN`, opens one
`AsyncDB("pg", dsn=…)` lazily in `_ensure()`, and `_ensure_table()` issues `CREATE TABLE IF NOT EXISTS` + `ALTER …
ADD COLUMN IF NOT EXISTS` + indexes once per table per process (cache `self._initialised`), after validating the
table name against `^[a-z_][a-z0-9_]*$`. Named columns (`crew_name`, `tenant` default `'global'`, …) sit next to
a `payload jsonb`. `save()` logs and swallows errors; `fetch()` re-raises. The table-name regex forbids a dot,
so a schema-qualified name like `navigator.crew_definitions` would be rejected if this helper were reused as-is.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py`
  lines: 15-26
  symbol: `_TABLE_RE`
  excerpt: |
    from parrot.conf import CREW_RESULT_STORAGE_PG_DSN
    _TABLE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
    _NAMED_COLUMNS = frozenset(("crew_name", "method", "user_id", "session_id", "timestamp", "execution_id", "tenant", "prompt"))
- path: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py`
  lines: 40-56
  symbol: `PostgresResultStorage._ensure`
  excerpt: |
    self._dsn = dsn or CREW_RESULT_STORAGE_PG_DSN
    if self._conn is None:
        self._conn = AsyncDB("pg", dsn=self._dsn)
        await self._conn.connection()
- path: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py`
  lines: 58-110
  symbol: `PostgresResultStorage._ensure_table`
  excerpt: |
    if not _TABLE_RE.match(table): raise ValueError(...)
    if table in self._initialised: return
    await conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (id uuid PRIMARY KEY DEFAULT gen_random_uuid(), ... payload jsonb NOT NULL)")
    await conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant TEXT NOT NULL DEFAULT 'global'")
- path: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py`
  lines: 112-162
  symbol: `PostgresResultStorage.save`
  excerpt: |
    except Exception as exc:
        self.logger.warning("PostgresResultStorage save failed for collection=%s: %s", collection, exc)
- path: `packages/ai-parrot/src/parrot/bots/flows/core/storage/backends/postgres.py`
  lines: 210-220
  symbol: `PostgresResultStorage.close`
  excerpt: |
    await self._conn.close(); self._conn = None; self._initialised.clear()

## Notes

Precedent for "the storage creates its own table at runtime" (contrast FW-008). DSN precedent: a dedicated conf
key (CREW_RESULT_STORAGE_PG_DSN) rather than BotManager's app["database"] pool.
[cross-lane: type=grep, intent=find CREW_RESULT_STORAGE_PG_DSN default in parrot/conf.py and whether a crew-definition DSN key should reuse it (Q013)]
