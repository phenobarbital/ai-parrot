---
title: PostgreSQL database migrations
summary: Deploy and verify packaged schemas, adopt existing databases, and keep migration ownership explicit.
---

# PostgreSQL database migrations

## Purpose

AI-Parrot ships versioned, checksummed PostgreSQL migrations inside its wheels and applies them with
`parrot self migration`. Use it to create the `BotModel` table on a fresh database, to upgrade a database that
was bootstrapped by hand-run SQL or by `creation.sql`, and to verify that a deployed schema still matches what
the installed software expects.

Schema migration is separate from `parrot self update`, which updates the software. Neither runs the other.

The commands operate on the Python environment in which `parrot` runs. They never dispatch to another virtualenv,
and they perform no DDL at application startup.

Ownership is explicit. The installed distributions contribute migration *sets*:

| Set | Distribution | Owned tables |
|---|---|---|
| `bots` (default) | `ai-parrot` | the configured `PARROT_SCHEMA.PARROT_BOTS_TABLE` |
| `ui_surfaces` | `ai-parrot-server` | `navigator.ui_surfaces`, `navigator.ui_surface_shares` |
| `crew_definitions` | `ai-parrot-server` | `navigator.crew_definitions` |
| `metric_definitions` | `ai-parrot-server` | `navigator.metric_definitions` |
| `recipes` | `ai-parrot-server` | `navigator.infographic_recipes` (default navigator schema only) |
| `scheduler` | `ai-parrot-server` | `navigator.service_scheduler` |

Server sets keep their fixed `navigator` targets even when `PARROT_SCHEMA` changes.

## Public API

- [Catalog](ref:parrot.migrations.catalog) — discovers installed sets through the `parrot.migrations` entry-point group,
  validates SQL/check pairs, computes checksums and scaffolds new files (`discover_sets`, `scaffold`).
- [Runner](ref:parrot.migrations.runner) — applies pending files and records baselines under one advisory lock
  (`upgrade`, `baseline`).
- [Read-only checks](ref:parrot.migrations.checks) — ledger and postcondition verification used by `status`, startup
  and doctor (`status`).

## Configuration & Parameters

### Commands and exit codes

Options go after the verb.

| Command | Behavior | Exit codes |
|---|---|---|
| `status [--set NAME ...] [--all] [--dsn DSN]` | Read-only. | `0` healthy · `1` pending, changed or postcondition drift · `2` database error or unknown ledger entry · `3` configuration |
| `upgrade [--set NAME ...] [--all] [--dsn DSN] [--fail-fast] [--reapply-changed]` | Applies pending files. | `0` healthy · `1` blocked by an unacknowledged changed file · `2` a migration failed · `3` configuration |
| `baseline --set NAME --through NNN [--dsn DSN]` | Records a verified prefix of one set without running SQL bodies. | same as `upgrade` |
| `new SET NAME --directory PATH` | Scaffolds a body/check pair locally. Needs no connection; `--dsn` is accepted but unused. | `3` on configuration errors |

`status` and `upgrade` accept `--connect-timeout` (5 s), `--lock-timeout` (30 s, `upgrade` only) and
`--statement-timeout` (60 s). `baseline` accepts the same three. All must be positive. Option and usage errors also
exit `3`.

Every run prints the selected sets, the target tables and the ledger (`<PARROT_SCHEMA>.parrot_schema_migrations`).

### Set selection

The default is `bots` only, so installing the server wheel never migrates optional stores by accident.
Repeat `--set NAME` to pick several sets, or pass `--all` to select every installed set on the one database you target.
`--all` and `--set` are mutually exclusive. An unknown or uninstalled set exits `3` with an install hint.

### DSN precedence and roles

- **Mutating commands** (`upgrade`, `baseline`): explicit `--dsn`, then `PARROT_ADMIN_DSN`, then the runtime
  `default_dsn`. Falling back to the runtime DSN logs a credential-free warning.
- **Read-only commands** (`status`, startup probe, doctor): explicit `--dsn`, then the runtime `default_dsn`.
  They never elevate to the admin DSN.
- A missing DSN is exit `3`.

Use an admin role for `upgrade` and `baseline`. The runtime role keeps its grants, which stay DBA-owned and are never
issued automatically: DML on the owned tables, `USAGE` on the schema, and `SELECT` on the ledger table. A permission
error is reported as an error, never as "pending" or "clean".

### Separate crew database

If `CREW_DEFINITION_PG_DSN` points at a different database, run the crew set explicitly against that database:

```bash
parrot self migration upgrade --set crew_definitions --dsn "$CREW_ADMIN_DSN"
```

## Usage Examples

### Deployment order

1. Take a backup.
2. Stop every writer, including application instances, so nothing competes with the migration. The advisory lock
   does not block application writes.
3. Upgrade:

   ```bash
   parrot self migration upgrade                       # bots only
   parrot self migration upgrade --set bots --set ui_surfaces
   parrot self migration upgrade --all --fail-fast
   ```

4. Verify; this is the deployment gate:

   ```bash
   parrot self migration status --all
   ```

5. Restart the application.

### Fresh install

`upgrade` creates the schema, the ledger and every selected table. `creation.sql` is a fresh-install-only
compatibility artifact and is not needed as a bootstrap.

### Adopting an existing database (partial adoption)

If the table already matches an earlier packaged file, record it without re-running anything. `baseline` verifies every
postcondition through the chosen sequence first and records rows only if all of them hold:

```bash
parrot self migration baseline --set bots --through 1
parrot self migration upgrade          # applies 002 onward
```

Baseline limits:

- It takes one explicit set and one explicit prefix. There is no `--force` bypass.
- It never executes SQL bodies and rejects changed or unknown ledger entries.
- Later files stay pending.
- Stamping is not a recovery tool. It asserts the schema is correct and cannot restore lost data.

### Changed-file repair

Published files are immutable, so a changed body or check is reported as CHANGED and blocks its set (exit `1`).
Fixes normally ship as a numbered successor. To replay on purpose:

```bash
parrot self migration upgrade --set bots --reapply-changed
```

Files are replayed in sequence, checksums are updated only after the body and its postcondition succeed, and the whole
set is rechecked afterwards.

### Authoring, scaffolding and wheels

```bash
parrot self migration new bots add_example_column --directory packages/ai-parrot/src/parrot/migrations/sql/bots
```

This creates `NNN_<name>.sql` and `NNN_<name>.check.sql` with `NNN` set to the highest existing number plus one.
The scaffolded check is `SELECT FALSE`, so an unfinished file can never be recorded as applied: replace it with a real
postcondition. A check returns exactly one boolean row and must stay true after later files run. Use the exact
`{schema}` and `{bots_table}` tokens only; they are validated against `[a-z_][a-z0-9_]{0,62}`.

Registering a new *set* is a separate step: add an entry under the `parrot.migrations` entry-point group in the
distribution's `pyproject.toml`, pointing at a factory that returns a `MigrationSet`, and ship the SQL as package data
(`"parrot.migrations" = ["sql/*/*.sql"]`). Entry points return metadata only. The core and server wheels are tested for
discovery and resource loading in isolated environments.

## Gotchas

- **`bots status` says nothing about Studio.** A healthy result covers only the selected sets. Studio and task memory
  are not checked by it.
- **Studio keeps its own migrations.** `studio_drafts` and `ai_skills_catalog` belong to Studio, which has its own
  runner:

  ```bash
  parrot-studio-migrate --dsn "$DSN" --dry-run     # also --verify
  ```

  Studio's `--stamp` rewrites release manifests and is not a database adoption baseline. Nothing in the generic ledger
  adopts these tables.
- **Task memory keeps its own migration owner.** See [Recoverable task memory](../memory/recoverable-task-memory.md).
  Flow result/checkpoint stores and knowledge-catalog schemas are not adopted as navigator tables either.
- **Runtime create-on-first-use paths still exist.** They never stamp the ledger, so a table created that way reads
  as pending until you `baseline` or `upgrade` it. Deploy with writers stopped.
- **Manual operations are not in the chain.** They ship under `sdd/migrations/` and never run automatically:
  - `users-bots-fold-embedding.sql` folds the `users_bots` embedding column, with relation and column guards.
  - `manual-bot-language-reset.sql` clears `language = 'en'` on both tables. It is lossy and changes stored
    preferences, so review it before running it.
  - `botmodel-recreate-table.sql` is destructive and carries a warning. Do not run it on a database whose data you
    need.
  The packaged bots chain never references `users_bots`.
- **Missing ledger means everything is pending.** An unknown ledger filename in a selected set is an error
  (possibly older software) and is never ignored or deleted.
- **Errors are credential-free.** Output carries the set, filename, SQLSTATE and a safe category, never DSNs, SQL
  bodies or driver text.
- **PostgreSQL 14 or newer is required.** `upgrade` and `baseline` take database-wide advisory lock `884000001`;
  `status`, startup and doctor take no lock and never create the ledger.
- **Startup and doctor only warn.** `BotManager` runs a bounded bots-only probe (2 s) when database bots are
  enabled, and `parrot self doctor` adds an informational check (5 s). Both fail open. Run `status` as the gate.

## Related

- [Recoverable task memory](../memory/recoverable-task-memory.md) — task memory has its own migration owner.
- [Task memory integration map](../memory/task-memory-integration-map.md) — where task-memory storage is wired in.
