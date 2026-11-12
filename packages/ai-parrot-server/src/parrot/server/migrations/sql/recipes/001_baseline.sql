-- Provenance: parrot.handlers.models.recipes._ddl_statements("navigator")
CREATE SCHEMA IF NOT EXISTS navigator;
CREATE TABLE IF NOT EXISTS navigator.infographic_recipes (
    name VARCHAR NOT NULL,
    owner VARCHAR NOT NULL DEFAULT '',
    schema_version INTEGER NOT NULL,
    title TEXT,
    description TEXT,
    recipe JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (name, owner)
);

DO $$
DECLARE
    required_column RECORD;
BEGIN
    FOR required_column IN
        SELECT *
        FROM (VALUES
            ('name', 'VARCHAR'),
            ('schema_version', 'INTEGER'),
            ('recipe', 'JSONB')
        ) AS columns(column_name, type_name)
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_attribute attribute
            WHERE attribute.attrelid = 'navigator.infographic_recipes'::regclass
              AND attribute.attname = required_column.column_name
              AND NOT attribute.attisdropped
        ) THEN
            IF EXISTS (SELECT 1 FROM navigator.infographic_recipes) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '42804',
                    MESSAGE = 'navigator.infographic_recipes is missing required columns';
            END IF;
            EXECUTE format(
                'ALTER TABLE navigator.infographic_recipes ADD COLUMN %I %s NOT NULL',
                required_column.column_name,
                required_column.type_name
            );
        END IF;
    END LOOP;
END $$;

ALTER TABLE navigator.infographic_recipes ADD COLUMN IF NOT EXISTS owner VARCHAR NOT NULL DEFAULT '';
ALTER TABLE navigator.infographic_recipes ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE navigator.infographic_recipes ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE navigator.infographic_recipes ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE navigator.infographic_recipes ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM (VALUES
            ('name', 'character varying', true),
            ('owner', 'character varying', true),
            ('schema_version', 'integer', true),
            ('title', 'text', false),
            ('description', 'text', false),
            ('recipe', 'jsonb', true),
            ('created_at', 'timestamp with time zone', true),
            ('updated_at', 'timestamp with time zone', true)
        ) AS required(column_name, type_name, not_null)
        LEFT JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = 'navigator.infographic_recipes'::regclass
         AND attribute.attname = required.column_name
         AND NOT attribute.attisdropped
        WHERE attribute.attnum IS NULL
           OR pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) <> required.type_name
           OR attribute.attnotnull <> required.not_null
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '42804',
            MESSAGE = 'navigator.infographic_recipes has incompatible columns';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint constraint_definition
        WHERE constraint_definition.conrelid = 'navigator.infographic_recipes'::regclass
          AND constraint_definition.contype = 'p'
          AND pg_catalog.pg_get_constraintdef(constraint_definition.oid) = 'PRIMARY KEY (name, owner)'
    ) THEN
        ALTER TABLE navigator.infographic_recipes
            ADD CONSTRAINT infographic_recipes_pkey PRIMARY KEY (name, owner);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_infographic_recipes_owner
    ON navigator.infographic_recipes (owner);
