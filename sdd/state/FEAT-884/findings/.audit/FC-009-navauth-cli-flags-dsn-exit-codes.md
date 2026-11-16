---
id: FC-009
query_id: Q010
type: read
intent: "Extract the navauth self upgrade CLI surface: flags, DSN resolution, exit codes, entry point."
executed_at: 2026-11-12T20:41:59Z
duration_ms: 300
parent_id: FC-006
depth: 1
---

# FC-009 — navauth CLI: argparse, --check, admin-DSN precedence, 4 exit codes

## Summary

`navauth self upgrade` is an argparse tree (`navauth` → `self` → `upgrade`) with `--check` (status only, exit 1 if
anything pending/changed or runtime grants missing), `--dsn`, `--user`, repeatable `--set`, `--runtime-role`
(default DBUSER), `--reapply-changed`, `--fail-fast`, `-v`. DSN precedence: `--dsn` > `AUTH_ADMIN_DSN` >
`--user`/`AUTH_ADMIN_USER` + `AUTH_ADMIN_PWD` (or TTY getpass) > runtime `default_dsn` (with a stderr notice).
Errors are sanitized (password/DSN redacted). Exit codes: 0 ok, 1 pending, 2 failed, 3 config. `connect` is injectable
for tests; connection is a raw `asyncpg.connect`.

## Citations

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

navauth uses argparse; parrot's `self` group is click (FC-013) — the CLI layer must be re-expressed, the runner can be
mirrored. The admin-vs-runtime role split exists because the runtime user may lack DDL rights; parrot conf has no
admin-DSN setting today (FC-015).
