---
id: F019
query_id: Q001
type: wiki_page
intent: "Read the reference spec for `navauth self upgrade` (design, ledger table, migration file format, CLI flags)."
executed_at: 2026-11-12T20:40:36Z
duration_ms: 2100
parent_id: null
depth: 0
merged_from: [FW-001]
---

# F019 — navauth self upgrade (navigator-auth FEAT-110): catalog + ledger + fail-closed runner + admin-DSN CLI

## Summary

Wiki page `navigator-auth::file:sdd/specs/new-command-migration.spec.md` (score 0.87; status approved, 2026-11-11).
Design: (1) **catalog** — SQL in `navigator_auth/migrations/sql/<set>/NNN_description.sql`, sets in fixed order
(vault, identity, passkey, mfa, oauth2), filename order inside a set, discovered from the filesystem (no
hand-written lists), `{schema}`/`{users_table}` placeholders rendered from config; (2) **ledger**
`<AUTH_DB_SCHEMA>.schema_migrations` keyed by `(migration_set, filename)` with sha256 checksum of raw bytes;
states applied / pending / changed (no ledger table ⇒ everything pending); (3) **runner** on a raw asyncpg
connection (asyncdb `execute()` returns errors instead of raising), session advisory lock, one transaction per
file (SQL + postcondition probes + runtime grants + ledger upsert), continue-on-failure, non-zero exit naming
failed files; (4) **CLI** argparse `navauth self upgrade [--check] [--dsn] [--user] [--set]… [--runtime-role]
[--reapply-changed] [--fail-fast] [-v]`; exit codes 0 ok · 1 --check found pending/changed · 2 a migration
failed · 3 usage/config/connection; DSN precedence `--dsn` → `AUTH_ADMIN_DSN` → `--user`/`AUTH_ADMIN_USER` +
`AUTH_ADMIN_PWD` (or TTY prompt) + DBHOST/DBPORT/DBNAME → `default_dsn` with a notice; secrets never printed;
(5) **startup** stops running DDL, only warns about pending files; (6) legacy `ensure_*` functions kept as shims.
**Pre-existing databases**: no baseline/fake flag — files must stay idempotent, the first run re-executes them
(no-ops) and records them. Non-goals: down/rollback migrations, data migrations, base-table creation, non-Postgres
DBs, external migration tools (not evaluated). No `--dry-run`/`--target` flags: `--check` is the dry run.

## Citations

- path: `../navigator-auth/sdd/specs/new-command-migration.spec.md`
  lines: 55-88
  symbol: `Goals / Non-Goals`
  excerpt: |
    G1 — A navauth console script with self upgrade … and self upgrade --check that only reports.
    G2 — One migration catalog: all SQL under navigator_auth/migrations/sql/<set>/ … no hand-written file lists.
    G3 — A ledger table recording each applied file (checksum, time, user, package version)
    G4 — Fail-closed execution · G5 — Admin credentials for DDL · G6 — startup stops running DDL; it checks and warns.
    Non-Goals: Down / rollback migrations. Data migrations … Adopting an external migration tool — not evaluated

- path: `../navigator-auth/sdd/specs/new-command-migration.spec.md`
  lines: 99-147
  symbol: `Overview`
  excerpt: |
    **First run on an existing database.** A database migrated by earlier startups has no ledger rows, so
    everything shows as pending. navauth self upgrade re-runs the idempotent files (no-ops on an up-to-date
    schema) and records them. This is why files must stay idempotent.

- path: `../navigator-auth/sdd/specs/new-command-migration.spec.md`
  lines: 180-260
  symbol: `schema_migrations ledger DDL / New Public Interfaces`
  excerpt: |
    CREATE TABLE IF NOT EXISTS {schema}.schema_migrations (
        migration_set VARCHAR(64) NOT NULL, filename VARCHAR(255) NOT NULL, checksum CHAR(64) NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), applied_by TEXT NOT NULL DEFAULT current_user,
        package_version VARCHAR(32), execution_ms INTEGER, PRIMARY KEY (migration_set, filename));
    GRANT SELECT ON {schema}.schema_migrations TO PUBLIC;

- path: `../navigator-auth/sdd/specs/new-command-migration.spec.md`
  lines: 391-420
  symbol: `Completion and retry contract`
  excerpt: |
    A successful execute() is necessary but insufficient for recording a file. … implement read-only
    prerequisite and postcondition probes … A guarded skip of required DDL is a failure.

- path: `../navigator-auth/sdd/specs/new-command-migration.spec.md`
  lines: 949-1000
  symbol: `Known Risks / Gotchas`
  excerpt: |
    asyncdb execute() never raises … Startup no longer migrates … Pre-ledger databases show everything as
    pending once … Advisory lock is session-level, so the whole run must use one connection …
    CREATE INDEX CONCURRENTLY cannot run inside the per-file transaction … checksums over raw bytes;
    the changed state is a warning, not an error

## Notes

Decisions recorded in its §8 (lines 1017-1033): SQL lives in-package (wheel ships it, `test_wheel_contains_sql`),
`docs/migrations/` holds README + index; per-set NNN numbering; ledger name + PUBLIC read grant. Observed root cause
in navauth (F008 there): loose DDL that no runner applies — same shape as parrot's `sdd/migrations/` (F020).
