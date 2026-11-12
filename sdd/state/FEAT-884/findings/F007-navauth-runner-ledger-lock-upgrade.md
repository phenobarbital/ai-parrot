---
id: F007
query_id: Q010, Q002, Q003
type: read + wiki_page
intent: "Read the navauth migration runner / ledger implementation to extract the contract to mirror. | Extract the navauth self upgrade CLI surface: flags, DSN resolution, exit codes, entry point. | Read the navauth upgrade CLI parser and follow edges to the migrations package (runner, registry, ledger)."
executed_at: 2026-11-12T20:41:59Z
duration_ms: 2800
parent_id: null
depth: 1
merged_from: [FC-007, FC-009, FW-002]
---

# F007 — navauth runner: checksum ledger, session advisory lock, one transaction per file, continue-on-failure

## Summary

`runner.py` keeps a ledger `<AUTH_DB_SCHEMA>.schema_migrations` keyed by `(migration_set, filename)` with sha256
`checksum`, `applied_by`, `package_version`, `execution_ms`. `get_status()` classifies each catalog file as
APPLIED / PENDING / CHANGED (checksum mismatch) without creating the ledger. `upgrade()` validates the runtime role,
takes `pg_try_advisory_lock(1102026)` with a 30 s retry, ensures the ledger (refusing if the base schema is missing —
"provisioned by the Navigator platform"), then applies each pending file in its own transaction (prereqs → SQL →
postconditions → GRANTs → ledger upsert). Failures roll back that file and the run continues unless `fail_fast`;
CHANGED files are skipped unless `reapply_changed`. Results come back as Pydantic `UpgradeReport`.

`navauth self upgrade` is an argparse tree (`navauth` → `self` → `upgrade`) with `--check` (status only, exit 1 if
anything pending/changed or runtime grants missing), `--dsn`, `--user`, repeatable `--set`, `--runtime-role`
(default DBUSER), `--reapply-changed`, `--fail-fast`, `-v`. DSN precedence: `--dsn` > `AUTH_ADMIN_DSN` >
`--user`/`AUTH_ADMIN_USER` + `AUTH_ADMIN_PWD` (or TTY getpass) > runtime `default_dsn` (with a stderr notice).
Errors are sanitized (password/DSN redacted). Exit codes: 0 ok, 1 pending, 2 failed, 3 config. `connect` is injectable
for tests; connection is a raw `asyncpg.connect`.

`navigator-auth::sym:navigator_auth/migrations/cli.py#build_parser` (score 0.80) builds an argparse parser with
`prog="navauth"`, a `self` sub-group ("manage this navigator-auth installation") and an `upgrade` command with
the flags of F019. `wikitoolkit related` on cli.py only lists its own symbols (`resolve_dsn`, `_build_dsn`,
`_default_connect`, `_print_status`, `_print_report`, `_sanitized_error`, `run`, `main`, `console_entry`).
One hop to `navigator-auth::file:navigator_auth/migrations/runner.py`: `LEDGER_TABLE="schema_migrations"`,
`ADVISORY_LOCK_KEY=1102026`, `LOCK_TIMEOUT_SECONDS=30`, `MigrationError`/`MigrationLockError`, pydantic
`MigrationState`/`MigrationStatus`/`MigrationResult`/`UpgradeReport`, `acquire_raw(db_pool)` (raw asyncpg conn from
an asyncpg or asyncdb pool), `execute_checked(conn, sql)` (translates asyncdb returned errors into exceptions),
`ledger_exists`, `ensure_ledger`, `get_status(conn, sets)` (never creates the ledger), `_apply_file` (one
transaction, never raises), `_reconcile_access` (runtime grants), `_acquire_lock` (retry until timeout),
`upgrade(conn, sets)`. Logger name `navigator.migrations`; `package_version` from `navigator_auth.version`.

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
    LEDGER_TABLE = "schema_migrations"
    ADVISORY_LOCK_KEY: int = 1102026
    LOCK_TIMEOUT_SECONDS: float = 30.0
    def execute_checked(conn, sql): Execute SQL and translate asyncdb's returned errors into exceptions.
    def get_status(conn, sets): Return each catalog file's ledger state without creating the ledger.
    def upgrade(conn, sets): Apply pending files (and changed ones when reapply_changed).

- path: `../navigator-auth/navigator_auth/migrations/runner.py`
  lines: 135-144
  symbol: `execute_checked`
  excerpt: |
    result = await conn.execute(sql, *args)
    if isinstance(result, (list, tuple)) and len(result) == 2 and result[1] is not None:
        raise MigrationError(f"Migration statement failed: {error}")

- path: `../navigator-auth/navigator_auth/migrations/cli.py`
  lines: 21-41
  symbol: `build_parser`
  excerpt: |
    EXIT_OK, EXIT_PENDING, EXIT_FAILED, EXIT_CONFIG = 0, 1, 2, 3
    up = commands.add_parser("upgrade", help="apply pending database migrations")
    up.add_argument("--check", action="store_true", help="report applied/pending/changed; change nothing")
    up.add_argument("--dsn", help="admin DSN (highest precedence)")
    up.add_argument("--set", dest="sets", action="append", choices=MIGRATION_SETS, ...)
    up.add_argument("--runtime-role", help="application database role; defaults to DBUSER")
    up.add_argument("--reapply-changed", ...); up.add_argument("--fail-fast", ...)

- path: `../navigator-auth/navigator_auth/migrations/cli.py`
  lines: 44-70
  symbol: `resolve_dsn`
  excerpt: |
    if args.dsn: return args.dsn, "--dsn"
    if conf.AUTH_ADMIN_DSN: return conf.AUTH_ADMIN_DSN, "AUTH_ADMIN_DSN"
    user = args.user or conf.AUTH_ADMIN_USER
    ...
    print("navauth: using runtime credentials from default_dsn", file=sys.stderr)
    return conf.default_dsn, "default_dsn"

- path: `../navigator-auth/navigator_auth/migrations/cli.py`
  lines: 98-112
  symbol: `_sanitized_error`
  excerpt: |
    message = str(error).replace(dsn, "[redacted DSN]")
    ...
    import asyncpg
    return await asyncpg.connect(dsn)

- path: `../navigator-auth/navigator_auth/migrations/cli.py`
  lines: 201-213
  symbol: `main`
  excerpt: |
    def main(argv=None, *, connect=None) -> int:
        args = build_parser().parse_args(argv)
        return asyncio.run(run(args, connect=connect))
    def console_entry() -> None:
        sys.exit(main())

## Notes

Works on a raw asyncpg connection (advisory lock is session-scoped, needs one stable connection); `acquire_raw`
unwraps asyncdb drivers. No down-migrations / rollback command exists — files are forward-only and idempotent.
Ledger has no sequence number: order = set order then filename. No "baseline/stamp" mode for pre-existing DBs —
idempotent DDL makes a first run against a populated DB a no-op instead.

navauth uses argparse; parrot's `self` group is click (F012) — the CLI layer must be re-expressed, the runner can be
mirrored. The admin-vs-runtime role split exists because the runtime user may lack DDL rights; parrot conf has no
admin-DSN setting today (F014).

navauth uses argparse + its own console script (first `[project.scripts]` entry); parrot's CLI is Click with a
LazyGroup (F012) — the structure transfers, the parser code does not. Tests: `navigator-auth::file:tests/unit/migrations/test_runner.py`
(score 0.57) and TASK-163 (`upgrade()` — advisory lock, per-file transaction, ledger upsert, access reconciliation).

[citation-check: stale] ../navigator-auth/navigator_auth/migrations/runner.py:278-287 — merged citation pairs the `upgrade` range with the `LEDGER_TABLE` excerpt; `LEDGER_TABLE = "schema_migrations"` is at line 23, `class MigrationState` at line 50, `pg_try_advisory_lock` at line 268.
