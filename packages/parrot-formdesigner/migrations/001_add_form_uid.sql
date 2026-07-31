-- Migration 001: Add form_uid to form_schemas (FEAT-389)
--
-- Adds the stable, immutable `form_uid` identity column to an EXISTING
-- `form_schemas` table (greenfield installs get it directly from
-- PostgresFormStorage._create_table_sql — see TASK-1974). Backfills
-- `form_uid` from the table's existing `id` UUID primary key (zero data
-- loss — `id` was always a UUID, just never exposed to the application
-- layer before this feature).
--
-- Idempotent: every statement is safe to run multiple times.
--
-- Usage (run once per physical schema — adjust search_path or qualify
-- table names for your deployment, e.g. multi-tenant schemas such as
-- `epson.form_schemas`, `pokemon.form_schemas`):
--
--   psql "$DSN" -c "SET search_path TO navigator;" -f 001_add_form_uid.sql
--
-- Or, to target a specific schema without changing search_path, qualify
-- `form_schemas` below as `<schema>.form_schemas` before running (a sed
-- replace or psql \set variable both work equally well here — this file
-- intentionally uses unqualified names to stay schema-agnostic).

-- ---------------------------------------------------------------------
-- Step 1: Add the column (nullable first — required for the backfill in
-- Step 2 to run against pre-existing rows before NOT NULL is enforced).
-- ---------------------------------------------------------------------
ALTER TABLE form_schemas ADD COLUMN IF NOT EXISTS form_uid VARCHAR(36);

-- ---------------------------------------------------------------------
-- Step 2: Backfill form_uid from the existing `id` UUID primary key.
-- Only touches rows that don't already have a form_uid — safe to rerun.
-- ---------------------------------------------------------------------
UPDATE form_schemas SET form_uid = id::text WHERE form_uid IS NULL;

-- ---------------------------------------------------------------------
-- Step 3: Enforce NOT NULL now that every row has a form_uid.
-- Idempotent: ALTER COLUMN ... SET NOT NULL is a no-op if already set.
-- ---------------------------------------------------------------------
-- NOTE (code-review fix): every guard below is scoped to the table actually
-- resolved by the CURRENT search_path (`table_schema = current_schema()` /
-- `conrelid = 'form_schemas'::regclass`) — NOT just a bare name match. This
-- migration is explicitly documented above to run once per physical
-- multi-tenant schema (`epson.form_schemas`, `pokemon.form_schemas`, ...).
-- An unscoped `WHERE table_name = 'form_schemas'` / `WHERE conname = '...'`
-- would see ANY schema's already-migrated table/constraint and silently
-- skip this schema's own — a real bug: e.g. `epson` migrated first would
-- make `pokemon`'s run silently no-op Steps 3-5, leaving `pokemon.
-- form_schemas.form_uid` nullable and unconstrained.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'form_schemas'
          AND column_name = 'form_uid'
          AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE form_schemas ALTER COLUMN form_uid SET NOT NULL;
    END IF;
END$$;

-- ---------------------------------------------------------------------
-- Step 4: Add the primary uniqueness constraint (form_uid, version).
-- ADD CONSTRAINT has no IF NOT EXISTS in all supported PG versions, so
-- guard via pg_constraint lookup inside a DO block.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'form_schemas'::regclass
          AND conname = 'uq_form_schemas_form_uid_version'
    ) THEN
        ALTER TABLE form_schemas ADD CONSTRAINT uq_form_schemas_form_uid_version
            UNIQUE (form_uid, version);
    END IF;
END$$;

-- ---------------------------------------------------------------------
-- Step 5: Add the secondary slug-uniqueness constraint
-- (tenant, form_id, version) — mirrors PostgresFormStorage's greenfield
-- DDL (TASK-1974) so migrated tables match freshly created ones.
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'form_schemas'::regclass
          AND conname = 'uq_form_schemas_tenant_form_id_version'
    ) THEN
        ALTER TABLE form_schemas ADD CONSTRAINT uq_form_schemas_tenant_form_id_version
            UNIQUE (tenant, form_id, version);
    END IF;
END$$;
