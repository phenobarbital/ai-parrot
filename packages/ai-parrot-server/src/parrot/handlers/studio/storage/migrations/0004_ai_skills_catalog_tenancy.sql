-- The table already exists on hosts that ran FEAT-467 (DDL only in the model docstring,
-- models/skills_catalog.py). Baseline first (FEAT-467 columns; a fresh table gets no global
-- UNIQUE(name) and gen_random_uuid() instead of uuid_generate_v4(), so it needs no
-- uuid-ossp extension), then extend in place. An existing table keeps its own defaults.
SELECT pg_advisory_xact_lock(4715391001);
CREATE TABLE IF NOT EXISTS navigator.ai_skills_catalog (
    skill_id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    name               varchar     NOT NULL,
    description        text        NOT NULL,
    category           varchar     NOT NULL DEFAULT 'general',
    owner              varchar     NOT NULL,
    triggers           jsonb       DEFAULT '[]'::jsonb,
    body               text        NOT NULL,
    version            integer     NOT NULL DEFAULT 1,
    status             varchar     NOT NULL DEFAULT 'active',
    search_index_stale boolean     NOT NULL DEFAULT false,
    created_at         timestamptz DEFAULT now(),
    updated_at         timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ai_skills_catalog_category ON navigator.ai_skills_catalog (category);
CREATE INDEX IF NOT EXISTS idx_ai_skills_catalog_owner    ON navigator.ai_skills_catalog (owner);
ALTER TABLE navigator.ai_skills_catalog ADD COLUMN IF NOT EXISTS tenant         text   NULL;
ALTER TABLE navigator.ai_skills_catalog ADD COLUMN IF NOT EXISTS visibility     text   NOT NULL DEFAULT 'private';
ALTER TABLE navigator.ai_skills_catalog ADD COLUMN IF NOT EXISTS allowed_groups text[] NOT NULL DEFAULT '{}';
-- Drop the FEAT-467 global UNIQUE(name), whatever the host named it: every unique
-- constraint whose key is exactly the single column `name`.
DO $$
DECLARE
    c record;
BEGIN
    FOR c IN
        SELECT con.conname
          FROM pg_constraint con
          JOIN pg_attribute att
            ON att.attrelid = con.conrelid AND att.attname = 'name'
         WHERE con.conrelid = 'navigator.ai_skills_catalog'::regclass
           AND con.contype = 'u'
           AND con.conkey = ARRAY[att.attnum]::int2[]
    LOOP
        EXECUTE format('ALTER TABLE navigator.ai_skills_catalog DROP CONSTRAINT %I', c.conname);
    END LOOP;
END $$;
-- ADD CONSTRAINT has no IF NOT EXISTS: each one is guarded on pg_constraint.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'navigator.ai_skills_catalog'::regclass
                      AND conname = 'ai_skills_catalog_tenant_name_key') THEN
        ALTER TABLE navigator.ai_skills_catalog
            ADD CONSTRAINT ai_skills_catalog_tenant_name_key UNIQUE (tenant, name);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'navigator.ai_skills_catalog'::regclass
                      AND conname = 'ai_skills_catalog_visibility_chk') THEN
        ALTER TABLE navigator.ai_skills_catalog
            ADD CONSTRAINT ai_skills_catalog_visibility_chk CHECK (visibility IN ('private','tenant','groups'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'navigator.ai_skills_catalog'::regclass
                      AND conname = 'ai_skills_catalog_tenant_chk') THEN
        ALTER TABLE navigator.ai_skills_catalog
            ADD CONSTRAINT ai_skills_catalog_tenant_chk CHECK (tenant IS NULL OR tenant ~ '^[a-z0-9][a-z0-9_-]{0,62}$');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'navigator.ai_skills_catalog'::regclass
                      AND conname = 'ai_skills_catalog_shared_needs_tenant_chk') THEN
        ALTER TABLE navigator.ai_skills_catalog
            ADD CONSTRAINT ai_skills_catalog_shared_needs_tenant_chk CHECK (tenant IS NOT NULL OR visibility = 'private');
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS ai_skills_catalog_global_name_uq ON navigator.ai_skills_catalog (name) WHERE tenant IS NULL;
CREATE INDEX IF NOT EXISTS ai_skills_catalog_tenant_visibility_idx ON navigator.ai_skills_catalog (tenant, visibility);
-- Existing rows: tenant NULL, visibility 'private'; they satisfy every new CHECK, and the
-- former global UNIQUE(name) guarantees the partial index builds.
-- @studio-ledger
INSERT INTO navigator.ai_studio_migrations (version, name, checksum)
VALUES (4, '0004_ai_skills_catalog_tenancy', '2654e092c29fc9ae09794ef74bf5570a910f7779163b8a7f95f82e656ed81168')
ON CONFLICT (version) DO NOTHING;
