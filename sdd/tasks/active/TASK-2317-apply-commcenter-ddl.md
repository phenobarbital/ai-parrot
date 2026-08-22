# TASK-2317: Apply CommCenter DDL (notification_templates + notification_batch_recipients)

**Feature**: commcenter-post-launch-fixes
**Feature ID**: FEAT-445
**Spec**: (follow-up to sdd/specs/commcenter-notify.spec.md — FEAT-417)
**Status**: [ ] pending
**Priority**: high
**Depends-on**: none
**Assigned-to**: unassigned

## Context

FEAT-417 authored two DDL files that create the tables CommCenter depends on,
but no code path in the repo applies them to any database.  The `.sql` files
sit in `packages/ai-parrot-server/src/parrot/handlers/models/` alongside the
Python models — this matches the broader `handlers/models/` convention where
DDL is shipped as reference but applied manually by ops.

Without the tables, template CRUD returns HTTP 500 and no real batch can be
tracked.

## Scope

1. Create a **Makefile target** (`make apply-commcenter-ddl`) that runs both
   SQL files against the `navigator` schema in order:
   - `notification_templates_creation.sql`
   - `notification_batches_creation.sql`
2. The target must accept a `DATABASE_URL` env-var (or fall back to the
   project's standard `NAVIGATOR_DSN` / `PG_URL`).
3. Add an idempotency guard — the DDL already uses `IF NOT EXISTS` / `DROP
   TRIGGER IF EXISTS`, so running twice must be safe; verify and document.
4. Document the step in `docs/comm_center.md` under a new **"Database setup"**
   section.

## Files to Create/Modify

- `Makefile` — new `apply-commcenter-ddl` target
- `docs/comm_center.md` — add database setup section

## Implementation Notes

- Look at existing Makefile targets for patterns (e.g. `make migrate`,
  `make setup-db` if they exist).
- The SQL files already live at well-known paths; the Makefile target can
  `cat` them and pipe to `psql`, or use `asyncdb`'s connection — whichever
  is the project convention.
- This is an **ops** task, not an application-code task.  No Python model
  changes needed.

## Acceptance Criteria

- [ ] `make apply-commcenter-ddl` runs both DDL files against a test database
      without error
- [ ] Running the target twice is idempotent (no errors on second run)
- [ ] `docs/comm_center.md` documents the setup step
- [ ] Template CRUD endpoints return 200/201 (not 500) after DDL is applied
