-- Provenance: parrot.handlers.crew.postgres_persistence._DDL_STATEMENTS
CREATE SCHEMA IF NOT EXISTS navigator;
CREATE TABLE IF NOT EXISTS navigator.crew_definitions (
    tenant TEXT NOT NULL DEFAULT 'global',
    name TEXT NOT NULL,
    crew_id TEXT NOT NULL,
    description TEXT,
    execution_mode VARCHAR(32),
    definition JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    PRIMARY KEY (tenant, name),
    CONSTRAINT uq_crew_definitions_tenant_crew_id UNIQUE (tenant, crew_id)
);

ALTER TABLE navigator.crew_definitions ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_attribute attribute
        WHERE attribute.attrelid = 'navigator.crew_definitions'::regclass
          AND attribute.attname IN ('tenant', 'name', 'crew_id', 'definition', 'created_at', 'updated_at')
          AND (attribute.attisdropped OR NOT attribute.attnotnull)
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '42804', MESSAGE = 'navigator.crew_definitions has incompatible required columns';
    END IF;
END $$;
