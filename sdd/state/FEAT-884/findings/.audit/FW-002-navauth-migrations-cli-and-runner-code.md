---
id: FW-002
query_id: Q002, Q003
type: wiki_page
intent: "Read the navauth upgrade CLI parser and follow edges to the migrations package (runner, registry, ledger)."
executed_at: 2026-11-12T20:40:36Z
duration_ms: 1800
parent_id: null
depth: 1
---

# FW-002 — navauth migrations package as implemented: argparse `self` group in cli.py, runner.py with advisory lock + ledger

## Summary

`navigator-auth::sym:navigator_auth/migrations/cli.py#build_parser` (score 0.80) builds an argparse parser with
`prog="navauth"`, a `self` sub-group ("manage this navigator-auth installation") and an `upgrade` command with
the flags of FW-001. `wikitoolkit related` on cli.py only lists its own symbols (`resolve_dsn`, `_build_dsn`,
`_default_connect`, `_print_status`, `_print_report`, `_sanitized_error`, `run`, `main`, `console_entry`).
One hop to `navigator-auth::file:navigator_auth/migrations/runner.py`: `LEDGER_TABLE="schema_migrations"`,
`ADVISORY_LOCK_KEY=1102026`, `LOCK_TIMEOUT_SECONDS=30`, `MigrationError`/`MigrationLockError`, pydantic
`MigrationState`/`MigrationStatus`/`MigrationResult`/`UpgradeReport`, `acquire_raw(db_pool)` (raw asyncpg conn from
an asyncpg or asyncdb pool), `execute_checked(conn, sql)` (translates asyncdb returned errors into exceptions),
`ledger_exists`, `ensure_ledger`, `get_status(conn, sets)` (never creates the ledger), `_apply_file` (one
transaction, never raises), `_reconcile_access` (runtime grants), `_acquire_lock` (retry until timeout),
`upgrade(conn, sets)`. Logger name `navigator.migrations`; `package_version` from `navigator_auth.version`.

## Citations

- path: `../navigator-auth/navigator_auth/migrations/cli.py`
  lines: 24-41
  symbol: `build_parser`
  excerpt: |
    parser = argparse.ArgumentParser(prog="navauth", description="navigator-auth administration")
    groups = parser.add_subparsers(dest="group", required=True)
    self_cmd = groups.add_parser("self", help="manage this navigator-auth installation")
    commands = self_cmd.add_subparsers(dest="command", required=True)
    up = commands.add_parser("upgrade", help="apply pending database migrations")
    up.add_argument("--check", action="store_true", help="report applied/pending/changed; change nothing")

- path: `../navigator-auth/navigator_auth/migrations/runner.py`
  lines: module header (wiki API outline, no line numbers)
  symbol: `upgrade`
  excerpt: |
    LEDGER_TABLE = "schema_migrations"
    ADVISORY_LOCK_KEY: int = 1102026
    LOCK_TIMEOUT_SECONDS: float = 30.0
    def execute_checked(conn, sql): Execute SQL and translate asyncdb's returned errors into exceptions.
    def get_status(conn, sets): Return each catalog file's ledger state without creating the ledger.
    def upgrade(conn, sets): Apply pending files (and changed ones when reapply_changed).

## Notes

navauth uses argparse + its own console script (first `[project.scripts]` entry); parrot's CLI is Click with a
LazyGroup (FW-003) — the structure transfers, the parser code does not. Tests: `navigator-auth::file:tests/unit/migrations/test_runner.py`
(score 0.57) and TASK-163 (`upgrade()` — advisory lock, per-file transaction, ledger upsert, access reconciliation).
