-- Migration 004: Retrofit form_uid column type VARCHAR(36) -> UUID (FEAT-393)
--
-- FEAT-389's 001_add_form_uid.sql / 002_add_form_uid_submissions.sql added
-- `form_uid` as VARCHAR(36) (application code always treated it as an
-- opaque string). This migration upgrades the COLUMN TYPE to native
-- Postgres UUID on both `form_schemas.form_uid` and `form_data.form_uid`,
-- now that the identity is genuinely UUID-typed end to end in the Python
-- layer (FEAT-393).
--
-- Idempotent: guarded via information_schema.columns — skips the ALTER
-- entirely once the column is already `uuid` typed.
--
-- Usage (same per-schema execution model as FEAT-389's migrations — run
-- once per physical Postgres schema, e.g. `navigator`, `epson`, `pokemon`):
--
--   psql "$DSN" -c "SET search_path TO navigator;" -f 004_form_uid_uuid_type.sql

-- ---------------------------------------------------------------------
-- form_schemas.form_uid: VARCHAR(36) -> UUID
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'form_schemas'
          AND column_name = 'form_uid'
          AND data_type <> 'uuid'
    ) THEN
        ALTER TABLE form_schemas
            ALTER COLUMN form_uid TYPE UUID USING form_uid::uuid;
    END IF;
END$$;

-- ---------------------------------------------------------------------
-- form_data.form_uid: VARCHAR(36) -> UUID
--
-- form_data.form_uid is nullable (orphaned submissions whose parent form
-- was deleted before FEAT-389's backfill ran) — NULL values cast to
-- NULL::uuid without error, so no separate guard is needed for that case.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'form_data'
          AND column_name = 'form_uid'
          AND data_type <> 'uuid'
    ) THEN
        ALTER TABLE form_data
            ALTER COLUMN form_uid TYPE UUID USING form_uid::uuid;
    END IF;
END$$;
