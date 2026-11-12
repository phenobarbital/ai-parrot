---
id: FC-007
query_id: Q010
type: read
intent: "Read the navauth migration runner / ledger implementation to extract the contract to mirror."
executed_at: 2026-11-12T20:41:18Z
duration_ms: 700
parent_id: FC-006
depth: 1
---

# FC-007 — navauth runner: checksum ledger, session advisory lock, one transaction per file, continue-on-failure

## Summary

`runner.py` keeps a ledger `<AUTH_DB_SCHEMA>.schema_migrations` keyed by `(migration_set, filename)` with sha256
`checksum`, `applied_by`, `package_version`, `execution_ms`. `get_status()` classifies each catalog file as
APPLIED / PENDING / CHANGED (checksum mismatch) without creating the ledger. `upgrade()` validates the runtime role,
takes `pg_try_advisory_lock(1102026)` with a 30 s retry, ensures the ledger (refusing if the base schema is missing —
"provisioned by the Navigator platform"), then applies each pending file in its own transaction (prereqs → SQL →
postconditions → GRANTs → ledger upsert). Failures roll back that file and the run continues unless `fail_fast`;
CHANGED files are skipped unless `reapply_changed`. Results come back as Pydantic `UpgradeReport`.

## Citations

- path: `../navigator-auth/navigator_auth/migrations/runner.py`
  lines: 23-39
  symbol: `_LEDGER_DDL`
  excerpt: |
    LEDGER_TABLE = "schema_migrations"
    ADVISORY_LOCK_KEY: int = 1102026
    CREATE TABLE IF NOT EXISTS {ledger} (
        migration_set VARCHAR(64) NOT NULL, filename VARCHAR(255) NOT NULL, checksum CHAR(64) NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), applied_by TEXT NOT NULL DEFAULT current_user,
        package_version VARCHAR(32), execution_ms INTEGER, PRIMARY KEY (migration_set, filename))

- path: `../navigator-auth/navigator_auth/migrations/runner.py`
  lines: 50-82
  symbol: `MigrationState`
  excerpt: |
    class MigrationState(str, Enum): APPLIED = "applied"; PENDING = "pending"; CHANGED = "changed"
    class MigrationStatus(BaseModel) / MigrationResult(BaseModel) / UpgradeReport(BaseModel):
        applied, failed, skipped_changed, access_errors

- path: `../navigator-auth/navigator_auth/migrations/runner.py`
  lines: 152-162
  symbol: `ensure_ledger`
  excerpt: |
    exists = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = $1)", AUTH_DB_SCHEMA)
    if not exists:
        raise MigrationError(f"Schema {AUTH_DB_SCHEMA!r} does not exist; it is provisioned by the Navigator platform")
    await execute_checked(conn, f"GRANT SELECT ON {ledger_name()} TO PUBLIC")

- path: `../navigator-auth/navigator_auth/migrations/runner.py`
  lines: 224-243
  symbol: `_apply_file`
  excerpt: |
    async with conn.transaction():
        await check_prerequisites(conn, file)
        await execute_checked(conn, render_sql(file.path.read_text(encoding="utf-8")))
        await check_postconditions(conn, file)
        await grant_runtime_access(conn, file.migration_set, runtime_role)
        await verify_runtime_access(conn, file.migration_set, runtime_role)
        await _upsert_ledger(conn, file, duration_ms)

- path: `../navigator-auth/navigator_auth/migrations/runner.py`
  lines: 260-275
  symbol: `_acquire_lock`
  excerpt: |
    if await conn.fetchval("SELECT pg_try_advisory_lock($1)", ADVISORY_LOCK_KEY): return
    raise MigrationLockError(f"Another migration run holds the advisory lock; gave up after {timeout:g}s. ...")

- path: `../navigator-auth/navigator_auth/migrations/runner.py`
  lines: 278-287
  symbol: `upgrade`
  excerpt: |
    async def upgrade(conn, sets=None, *, runtime_role: str, reapply_changed: bool = False,
                      fail_fast: bool = False, lock_timeout: float = LOCK_TIMEOUT_SECONDS,
                      lock_poll: float = LOCK_POLL_SECONDS) -> UpgradeReport:

- path: `../navigator-auth/navigator_auth/migrations/runner.py`
  lines: 135-144
  symbol: `execute_checked`
  excerpt: |
    result = await conn.execute(sql, *args)
    if isinstance(result, (list, tuple)) and len(result) == 2 and result[1] is not None:
        raise MigrationError(f"Migration statement failed: {error}")

## Notes

Works on a raw asyncpg connection (advisory lock is session-scoped, needs one stable connection); `acquire_raw`
unwraps asyncdb drivers. No down-migrations / rollback command exists — files are forward-only and idempotent.
Ledger has no sequence number: order = set order then filename. No "baseline/stamp" mode for pre-existing DBs —
idempotent DDL makes a first run against a populated DB a no-op instead.
