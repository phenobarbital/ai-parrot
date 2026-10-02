SELECT pg_advisory_xact_lock(4715391001);
CREATE TABLE IF NOT EXISTS navigator.ai_agent_drafts (
    draft_id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant             text        NULL,
    owner              text        NOT NULL,
    name               text        NOT NULL,
    visibility         text        NOT NULL DEFAULT 'private',
    allowed_groups     text[]      NOT NULL DEFAULT '{}',
    definition         jsonb       NOT NULL,     -- StudioAgentBundle (definition + tooling + assets)
    validation         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status             text        NOT NULL DEFAULT 'draft',
    version            integer     NOT NULL DEFAULT 1,
    activated_agent_id uuid        NULL REFERENCES navigator.ai_agents(agent_id) ON DELETE SET NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ai_agent_drafts_visibility_chk CHECK (visibility IN ('private','tenant','groups')),
    CONSTRAINT ai_agent_drafts_status_chk     CHECK (status IN ('draft','validated','failed','activated')),
    CONSTRAINT ai_agent_drafts_name_chk       CHECK (name ~ '^[a-z0-9_-]{1,64}$'),
    CONSTRAINT ai_agent_drafts_tenant_chk     CHECK (tenant IS NULL OR tenant ~ '^[a-z0-9][a-z0-9_-]{0,62}$'),
    CONSTRAINT ai_agent_drafts_shared_needs_tenant_chk CHECK (tenant IS NOT NULL OR visibility = 'private'),
    CONSTRAINT ai_agent_drafts_definition_chk CHECK (jsonb_typeof(definition) = 'object'),
    CONSTRAINT ai_agent_drafts_tenant_name_key UNIQUE (tenant, name)
);
CREATE UNIQUE INDEX IF NOT EXISTS ai_agent_drafts_global_name_uq ON navigator.ai_agent_drafts (name) WHERE tenant IS NULL;
CREATE INDEX IF NOT EXISTS ai_agent_drafts_tenant_owner_idx ON navigator.ai_agent_drafts (tenant, owner);
CREATE OR REPLACE TRIGGER ai_agent_drafts_bump_version_trg
    BEFORE UPDATE ON navigator.ai_agent_drafts
    FOR EACH ROW EXECUTE FUNCTION navigator.ai_studio_bump_version();
-- @studio-ledger
INSERT INTO navigator.ai_studio_migrations (version, name, checksum)
VALUES (3, '0003_ai_agent_drafts', '405307336f1fad11b659bf7a5dda643f3b2b26e2cabfbbdfaac801d2117b6e8b')
ON CONFLICT (version) DO NOTHING;
