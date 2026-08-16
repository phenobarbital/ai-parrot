-- Migration 002: Add form_uid to form_data (submissions) (FEAT-389)
--
-- Adds `form_uid` to the `form_data` (FormSubmission) table and backfills
-- it via a JOIN against the now-migrated `form_schemas` table (run
-- 001_add_form_uid.sql FIRST — this migration depends on form_schemas
-- already having a populated `form_uid` column).
--
-- Rows in `form_data` whose `form_id` has no matching row in
-- `form_schemas` (the parent form was deleted) are left with
-- `form_uid IS NULL` — these are orphans. `003_migrate_form_data.py`
-- reports them; this SQL migration does not fail or delete them.
--
-- Idempotent: every statement is safe to run multiple times.
--
-- Usage (same schema-qualification note as 001_add_form_uid.sql applies —
-- run against the SAME schema for both form_schemas and form_data):
--
--   psql "$DSN" -c "SET search_path TO navigator;" -f 002_add_form_uid_submissions.sql

-- ---------------------------------------------------------------------
-- Step 1: Add the column (nullable — orphaned submissions will keep it
-- NULL; NOT NULL is deliberately never enforced on form_data.form_uid).
-- ---------------------------------------------------------------------
ALTER TABLE form_data ADD COLUMN IF NOT EXISTS form_uid VARCHAR(36);

-- ---------------------------------------------------------------------
-- Step 2: Backfill form_uid via JOIN against form_schemas on form_id.
-- Only touches rows that don't already have a form_uid — safe to rerun.
--
-- NOTE: if the same form_id exists under multiple form_uids (e.g. a
-- deleted-and-recreated form reusing the same slug), this JOIN may match
-- more than one form_schemas row per form_data row. Postgres's UPDATE ...
-- FROM picks an arbitrary match in that case. `003_migrate_form_data.py`
-- performs the same backfill with explicit tie-breaking (most recently
-- created form_schemas row wins) — prefer the Python script for
-- production backfills where this ambiguity is a concern.
-- ---------------------------------------------------------------------
UPDATE form_data fd
SET form_uid = fs.form_uid
FROM form_schemas fs
WHERE fd.form_id = fs.form_id
  AND fd.form_uid IS NULL;

-- ---------------------------------------------------------------------
-- Step 3: Index for form_uid-based submission lookups.
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_form_data_form_uid ON form_data(form_uid);
