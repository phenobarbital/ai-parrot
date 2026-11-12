---
id: FG-001
query_id: Q017
type: git_log
intent: "History of navauth migrations package — how the feature landed and evolved."
executed_at: 2026-11-12T20:39:39Z
duration_ms: 1800
parent_id: null
depth: 0
---

# FG-001 — navauth migrations package landed in one day (FEAT-110, 2026-11-11) with one hardening fix

## Summary

In ../navigator-auth, `navauth self upgrade` is FEAT-110 `new-command-migration`: spec added 2026-11-11 (788cab0, 951 lines; Qs resolved 1a78a47), implemented the same day as TASK-159..170 by the SDD engine, and hardened 2026-11-12 (089ff13: bounded upgrade lock, startup warning scoped to enabled sets, quoted CLI DSN). The package `navigator_auth/migrations/` is: `catalog.py` (migration discovery), `runner.py` (upgrade(), lock), `access.py`, `checks.py` (post-migration checks), `cli.py` (parser), `startup.py` (startup warning when pending), plus versioned SQL under `sql/<set>/NNN_<name>.sql` grouped by feature set (identity 001-006, mfa 001-002, oauth2 001, passkey 001, vault 001-002). Very fresh code — expect the design to still be settling.

## Citations

- path: `/home/jesuslara/proyectos/navigator-auth/navigator_auth/migrations/catalog.py`
  lines: n/a (git)
  symbol: null
  excerpt: |
    ec145bf 2026-11-11 feat(new-command-migration): TASK-159 — adds __init__.py, catalog.py (117 lines)
    and 9 SQL files: sql/identity/001..006, sql/passkey/001, sql/vault/001..002

- path: `/home/jesuslara/proyectos/navigator-auth/navigator_auth/migrations/runner.py`
  lines: n/a (git)
  symbol: `upgrade`
  excerpt: |
    14a47fb TASK-160 — runner.py (187 lines) added
    d2bd94a TASK-163 — "migration upgrade()" (+124 runner.py)
    089ff13 2026-11-12 fix: bounded upgrade lock (+46/-? runner.py)

- path: `/home/jesuslara/proyectos/navigator-auth/navigator_auth/migrations/access.py`
  lines: n/a (git)
  symbol: null
  excerpt: |
    933b7d6 TASK-162 — access.py (181 lines) added; c4a288e TASK-170 modified

- path: `/home/jesuslara/proyectos/navigator-auth/navigator_auth/migrations/checks.py`
  lines: n/a (git)
  symbol: null
  excerpt: |
    9de4661 TASK-161 — checks.py (226 lines) added

- path: `/home/jesuslara/proyectos/navigator-auth/navigator_auth/migrations/cli.py`
  lines: n/a (git)
  symbol: `build_parser`
  excerpt: |
    47625aa TASK-165 — cli.py (188 lines) added
    82b97ba fix: CLI maps unexpected DB errors to EXIT_FAILED, not traceback/exit 1
    089ff13 fix: quoted CLI DSN

- path: `/home/jesuslara/proyectos/navigator-auth/navigator_auth/migrations/startup.py`
  lines: n/a (git)
  symbol: null
  excerpt: |
    86a7944 TASK-166 — startup.py (63 lines) added
    089ff13 fix: startup warning scoped to enabled sets

- path: `/home/jesuslara/proyectos/navigator-auth/navigator_auth/migrations/sql/`
  lines: n/a (git)
  symbol: null
  excerpt: |
    identity/001_identity_credentials.sql … 006_identity_drop_legacy_uid.sql
    mfa/001_mfa_tables.sql, mfa/002_mfa_secrets.sql   (c4a288e TASK-170)
    oauth2/001_oauth2_schema.sql                        (834b471 TASK-167, 219 lines)
    passkey/001_passkey_credentials.sql
    vault/001_create_vault_tables.sql, vault/002_vault_crypto_hardening.sql

- path: `/home/jesuslara/proyectos/navigator-auth/sdd/specs/new-command-migration.spec.md`
  lines: n/a (git)
  symbol: null
  excerpt: |
    788cab0 2026-11-11 sdd: add spec for FEAT-110 — new-command-migration (951 lines)
    0f75a76 identity tests (+131/-18); 1a78a47 resolve open questions (+54/-26)

## Notes

- Layout to mirror: `<pkg>/migrations/{catalog,runner,access,checks,cli,startup}.py` + `sql/<set>/<NNN>_<name>.sql` (numbered per set, not global).
- Post-ship fixes (lock bounding, DSN quoting, error→exit code mapping, startup-warning scope) are lessons parrot's version should bake in from day one.
- [cross-lane: type=read, intent=read navigator_auth/migrations/runner.py and catalog.py for the ledger table name, lock mechanism and checksum rules]
