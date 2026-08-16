-- Migration 005: field_bank column rename field_id -> question_id (FEAT-393)
--
-- The QuestionBankService bank-entry identifier had no relation to
-- FormField.field_id and the naming collision was a source of confusion —
-- TASK-2006 renames the Python model/DDL/SQL to `question_id`. This
-- migration renames the EXISTING `field_bank.field_id` column (and its
-- UNIQUE(field_id, tenant) constraint) to `question_id` on already-deployed
-- installs. Greenfield installs already get `question_id` directly from
-- `QuestionBankService._ensure_table()` (TASK-2006).
--
-- Idempotent: guarded via information_schema.columns / pg_constraint —
-- skips entirely once already renamed.
--
-- Usage (same per-schema execution model as FEAT-389's migrations — run
-- once per physical Postgres schema, e.g. `navigator`, `epson`, `pokemon`):
--
--   psql "$DSN" -c "SET search_path TO navigator;" -f 005_question_bank_question_id.sql

-- ---------------------------------------------------------------------
-- Step 1: Rename the column, only if the OLD name still exists and the
-- NEW name does not (guards against a partial/interrupted prior run).
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'field_bank'
          AND column_name = 'field_id'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'field_bank'
          AND column_name = 'question_id'
    ) THEN
        ALTER TABLE field_bank RENAME COLUMN field_id TO question_id;
    END IF;
END$$;

-- ---------------------------------------------------------------------
-- Step 2: Rename the UNIQUE(field_id, tenant) constraint to match
-- Postgres's default auto-generated name for the OLD column, only if it
-- still exists under that name.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'field_bank'::regclass
          AND conname = 'field_bank_field_id_tenant_key'
    ) THEN
        ALTER TABLE field_bank
            RENAME CONSTRAINT field_bank_field_id_tenant_key TO field_bank_question_id_tenant_key;
    END IF;
END$$;
