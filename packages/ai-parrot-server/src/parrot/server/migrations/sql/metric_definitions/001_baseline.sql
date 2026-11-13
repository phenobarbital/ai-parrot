-- Provenance: parrot.handlers.models.metric_definitions._DDL_STATEMENTS
CREATE SCHEMA IF NOT EXISTS navigator;
CREATE TABLE IF NOT EXISTS navigator.metric_definitions (
    metric_id VARCHAR(63) NOT NULL,
    tenant VARCHAR(63) NULL,
    name TEXT NOT NULL,
    owner VARCHAR NULL,
    visibility VARCHAR(16) NOT NULL DEFAULT 'tenant',
    allowed_groups JSONB NOT NULL DEFAULT '[]'::jsonb,
    global_only BOOLEAN NOT NULL DEFAULT FALSE,
    program VARCHAR NULL,
    definition JSONB NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant, metric_id),
    CHECK (tenant IS NOT NULL OR visibility <> 'tenant')
);

-- Required columns without safe values may be adopted only while an existing
-- table is empty.  Populated incompatible tables fail without rewriting rows.
DO $$
DECLARE
    required_column RECORD;
BEGIN
    FOR required_column IN
        SELECT *
        FROM (VALUES
            ('metric_id', 'VARCHAR(63)'),
            ('name', 'TEXT'),
            ('definition', 'JSONB')
        ) AS columns(column_name, type_name)
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_attribute attribute
            WHERE attribute.attrelid = 'navigator.metric_definitions'::regclass
              AND attribute.attname = required_column.column_name
              AND NOT attribute.attisdropped
        ) THEN
            IF EXISTS (SELECT 1 FROM navigator.metric_definitions) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '42804',
                    MESSAGE = 'navigator.metric_definitions is missing required columns';
            END IF;
            EXECUTE format(
                'ALTER TABLE navigator.metric_definitions ADD COLUMN %I %s NOT NULL',
                required_column.column_name,
                required_column.type_name
            );
        END IF;
    END LOOP;
END $$;

ALTER TABLE navigator.metric_definitions ADD COLUMN IF NOT EXISTS tenant VARCHAR(63) NULL;
ALTER TABLE navigator.metric_definitions ADD COLUMN IF NOT EXISTS owner VARCHAR NULL;
ALTER TABLE navigator.metric_definitions ADD COLUMN IF NOT EXISTS visibility VARCHAR(16) NOT NULL DEFAULT 'tenant';
ALTER TABLE navigator.metric_definitions ADD COLUMN IF NOT EXISTS allowed_groups JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE navigator.metric_definitions ADD COLUMN IF NOT EXISTS global_only BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE navigator.metric_definitions ADD COLUMN IF NOT EXISTS program VARCHAR NULL;
ALTER TABLE navigator.metric_definitions ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE navigator.metric_definitions ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE navigator.metric_definitions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM (VALUES
            ('metric_id', 'character varying(63)', true),
            ('tenant', 'character varying(63)', false),
            ('name', 'text', true),
            ('owner', 'character varying', false),
            ('visibility', 'character varying(16)', true),
            ('allowed_groups', 'jsonb', true),
            ('global_only', 'boolean', true),
            ('program', 'character varying', false),
            ('definition', 'jsonb', true),
            ('version', 'integer', true),
            ('created_at', 'timestamp with time zone', true),
            ('updated_at', 'timestamp with time zone', true)
        ) AS required(column_name, type_name, not_null)
        LEFT JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = 'navigator.metric_definitions'::regclass
         AND attribute.attname = required.column_name
         AND NOT attribute.attisdropped
        WHERE attribute.attnum IS NULL
           OR pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) <> required.type_name
           OR attribute.attnotnull <> required.not_null
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '42804',
            MESSAGE = 'navigator.metric_definitions has incompatible columns';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint constraint_definition
        WHERE constraint_definition.conrelid = 'navigator.metric_definitions'::regclass
          AND constraint_definition.contype = 'u'
          AND pg_catalog.pg_get_constraintdef(constraint_definition.oid) = 'UNIQUE (tenant, metric_id)'
    ) THEN
        ALTER TABLE navigator.metric_definitions
            ADD CONSTRAINT metric_definitions_tenant_metric_id_uq UNIQUE (tenant, metric_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint constraint_definition
        WHERE constraint_definition.conrelid = 'navigator.metric_definitions'::regclass
          AND constraint_definition.contype = 'c'
          AND pg_catalog.pg_get_constraintdef(constraint_definition.oid)
              LIKE '%tenant IS NOT NULL%visibility%tenant%'
    ) THEN
        ALTER TABLE navigator.metric_definitions
            ADD CONSTRAINT metric_definitions_global_visibility_ck
            CHECK (tenant IS NOT NULL OR visibility <> 'tenant');
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS metric_definitions_global_uq
    ON navigator.metric_definitions (metric_id) WHERE tenant IS NULL;
CREATE INDEX IF NOT EXISTS metric_definitions_tenant_vis_idx
    ON navigator.metric_definitions (tenant, visibility);
CREATE INDEX IF NOT EXISTS metric_definitions_program_idx
    ON navigator.metric_definitions (program);
