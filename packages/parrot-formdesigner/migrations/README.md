# parrot-formdesigner migrations (FEAT-389)

Standalone SQL + Python migration artifacts for existing PostgreSQL
installs adopting the stable UUID form identity (`form_uid`) feature.

There is no migration framework (no Alembic, no schema-version table) —
these are plain, idempotent scripts meant to be run manually, once, per
physical Postgres schema. **Greenfield installs do not need these** —
`PostgresFormStorage._create_table_sql` (TASK-1974) already creates new
tables with `form_uid` from the start.

## Prerequisites

- The application code has already been deployed with FEAT-389 (or is
  about to be — running the migrations does not require the app to be
  stopped, but forms saved via the OLD `form_id`-keyed code path between
  migration and deploy will not have gone through `form_uid` reindexing
  in the registry; keep the deploy window short).
- **Check for pre-existing duplicate `(tenant, form_id, version)` rows
  before running `001_add_form_uid.sql`** — its final step adds a
  `UNIQUE(tenant, form_id, version)` constraint, which will fail if such
  duplicates already exist. Query first:
  ```sql
  SELECT tenant, form_id, version, COUNT(*)
  FROM form_schemas
  GROUP BY tenant, form_id, version
  HAVING COUNT(*) > 1;
  ```
  Resolve any duplicates (manually, or via an app-specific cleanup) before
  proceeding.
- `asyncpg` installed in the environment running `003_migrate_form_data.py`
  (already a dependency of `parrot_formdesigner`).

## Execution order

Run once per physical Postgres schema (e.g. `navigator`, `epson`,
`pokemon` — every tenant's schema that has its own `form_schemas` /
`form_data` tables):

1. **`001_add_form_uid.sql`** — adds `form_uid` to `form_schemas`,
   backfills it from the existing `id` UUID primary key, and adds the
   `UNIQUE(form_uid, version)` + `UNIQUE(tenant, form_id, version)`
   constraints.

   ```bash
   psql "$DSN" -c "SET search_path TO navigator;" -f 001_add_form_uid.sql
   ```

2. **`002_add_form_uid_submissions.sql`** — adds `form_uid` to
   `form_data` and backfills it via a JOIN against the now-migrated
   `form_schemas` table. **Must run after step 1** in the SAME schema.

   ```bash
   psql "$DSN" -c "SET search_path TO navigator;" -f 002_add_form_uid_submissions.sql
   ```

   Note: this SQL-only backfill picks an arbitrary `form_schemas` match
   when a `form_id` slug maps to more than one `form_uid` (e.g. a deleted
   and recreated form reusing the same slug). If you need deterministic
   tie-breaking (most recently created form wins) or an explicit orphan
   report, use step 3 instead of (or in addition to) this file.

3. **`003_migrate_form_data.py`** — Python script performing the same
   `form_data.form_uid` backfill in batches, with deterministic
   tie-breaking and an orphan report (submissions whose `form_id` has no
   matching `form_schemas` row — the parent form was deleted). Safe to
   run even if step 2 already ran (idempotent — only touches rows still
   missing `form_uid`).

   ```bash
   # Dry run first — prints the report without writing anything.
   python 003_migrate_form_data.py --dsn "$DSN" --schema navigator --dry-run

   # Then for real:
   python 003_migrate_form_data.py --dsn "$DSN" --schema navigator
   ```

Repeat all three steps for every tenant schema in your deployment.

4. **`004_form_uid_uuid_type.sql`** / **`005_question_bank_question_id.sql`**
   — FEAT-393 column retrofits (`form_uid` `str` → `uuid`, question bank
   `field_id` → `question_id`).

5. **`006_backfill_element_uids.py`** — mints and persists
   `field_uid`/`section_uid`/`subsection_uid` into every `schema_json`
   document and rewrites rule references from authored `field_id` to
   `field_uid`. Also reports (never rewrites) `form_data` blob_refs still
   on the legacy `{form_id}/{field_id}/` object-store key pattern.

   ```bash
   python 006_backfill_element_uids.py --dsn "$DSN" --schema navigator --dry-run
   python 006_backfill_element_uids.py --dsn "$DSN" --schema navigator
   ```

   **Read the "Skipped (duplicate field_id)" section of its report.**
   Those rows were NOT migrated — see step 6.

6. **`007_dedupe_duplicate_field_ids.py`** — repairs exactly the rows
   step 5 skipped. Renames colliding `field_id`s (first occurrence keeps
   its name; later ones become `{field_id}__2`, `__3`, …), then finishes
   step 5's UID backfill and rule-reference rewrite on the now-valid
   document.

   Unlike the other scripts this one **reports by default** and writes
   only when passed `--apply`:

   ```bash
   # Report only — no writes.
   python 007_dedupe_duplicate_field_ids.py --dsn "$DSN" --schema navigator
   # Apply.
   python 007_dedupe_duplicate_field_ids.py --dsn "$DSN" --schema navigator --apply
   ```

## Why duplicate `field_id`s exist at all

`FormSchema` gained a model-level, full-tree `field_id` uniqueness
validator on 2026-07-31 (`TASK-1996`, FEAT-393). Before it, the only
uniqueness check was **per-section and on the edit path only**
(`api/operations.py::_check_unique_field_id`), so a `field_id` repeated
across two different sections was legal and persisted cleanly. Because
the validator runs on `model_validate()`, it now runs on every *load* —
which turns such a stored document into a form that
`PostgresFormStorage.load()` logs, returns `None` for, and
`FormRegistry.load_from_storage()` silently drops at startup. The form
reads as deleted rather than broken.

The networkninja importer stopped *producing* these on 2026-08-20
(`seen_columns`, `tools/services/networkninja.py`), but nothing repaired
the documents already in Postgres. Step 6 is that repair.

## Idempotency

Every statement in `001_add_form_uid.sql` and
`002_add_form_uid_submissions.sql` is safe to re-run:
`ADD COLUMN IF NOT EXISTS`, `WHERE form_uid IS NULL` backfill guards,
`DO $$ ... IF NOT EXISTS ...` constraint blocks, and
`CREATE INDEX IF NOT EXISTS`. `003_migrate_form_data.py` only ever
touches rows where `form_uid IS NULL`, so re-running after a partial or
interrupted run resumes safely without reprocessing already-backfilled
rows or duplicating orphan reports. `006_backfill_element_uids.py` only
issues an UPDATE when the migrated document differs from the stored one,
and `007_dedupe_duplicate_field_ids.py` reports an already-valid document
as `already_valid` and never rewrites it — so both are safe to re-run.

## Orphans

A `form_data` row is "orphaned" if its `form_id` has no matching row in
`form_schemas` — the form it was submitted against was later deleted.
Orphaned rows are left with `form_uid IS NULL` permanently (there is
nothing to backfill from) and are listed by `003_migrate_form_data.py`'s
report for manual review. Neither migration deletes or otherwise
modifies orphaned rows.
