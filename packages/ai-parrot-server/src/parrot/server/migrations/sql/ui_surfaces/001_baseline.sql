-- Provenance: parrot.handlers.models.ui_surfaces._DDL_STATEMENTS
CREATE SCHEMA IF NOT EXISTS navigator;
CREATE TABLE IF NOT EXISTS navigator.ui_surfaces (
    surface_id UUID PRIMARY KEY,
    kind VARCHAR(32) NOT NULL,
    title TEXT NOT NULL,
    envelope JSONB NOT NULL,
    catalog_id VARCHAR,
    agent_id VARCHAR NOT NULL,
    user_id VARCHAR NOT NULL,
    session_id VARCHAR,
    recipe_name VARCHAR,
    recipe_owner VARCHAR,
    recipe_params JSONB NOT NULL DEFAULT '{}'::jsonb,
    tenant VARCHAR(63),
    visibility VARCHAR(16) NOT NULL DEFAULT 'private',
    allowed_groups JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS navigator.ui_surface_shares (
    token TEXT PRIMARY KEY,
    surface_id UUID NOT NULL REFERENCES navigator.ui_surfaces(surface_id) ON DELETE CASCADE,
    permissions VARCHAR(32) NOT NULL DEFAULT 'read+refresh',
    expires_at TIMESTAMPTZ,
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    claimed_by TEXT,
    claimed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- These are the only additive runtime changes.  They precede the index which
-- uses them so a pre-FEAT-535 table is safe to adopt.
ALTER TABLE navigator.ui_surfaces ADD COLUMN IF NOT EXISTS tenant VARCHAR(63);
ALTER TABLE navigator.ui_surfaces ADD COLUMN IF NOT EXISTS visibility VARCHAR(16) NOT NULL DEFAULT 'private';
ALTER TABLE navigator.ui_surfaces ADD COLUMN IF NOT EXISTS allowed_groups JSONB NOT NULL DEFAULT '[]'::jsonb;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_attribute attribute
        WHERE attribute.attrelid = 'navigator.ui_surfaces'::regclass
          AND attribute.attname IN ('surface_id', 'kind', 'title', 'envelope', 'agent_id', 'user_id')
          AND (
              attribute.attisdropped
              OR (attribute.attname = 'surface_id' AND attribute.atttypid <> 'uuid'::regtype)
              OR (attribute.attname IN ('kind', 'title', 'envelope', 'agent_id', 'user_id') AND NOT attribute.attnotnull)
          )
    ) THEN
        RAISE EXCEPTION USING ERRCODE = '42804', MESSAGE = 'navigator.ui_surfaces has incompatible required columns';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_ui_surfaces_user ON navigator.ui_surfaces (user_id);
CREATE INDEX IF NOT EXISTS ix_ui_surfaces_user_kind ON navigator.ui_surfaces (user_id, kind);
CREATE INDEX IF NOT EXISTS ix_ui_surfaces_tenant_visibility ON navigator.ui_surfaces (tenant, visibility);
CREATE INDEX IF NOT EXISTS ix_ui_surface_shares_surface ON navigator.ui_surface_shares (surface_id);
CREATE INDEX IF NOT EXISTS ix_ui_surface_shares_claimed_by ON navigator.ui_surface_shares (claimed_by);
