SELECT pg_advisory_xact_lock(4715391001);
CREATE TABLE IF NOT EXISTS navigator.ai_agents (
    agent_id        uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant          text        NULL,         -- NULL = non-tenant host (GLOBAL partition)
    name            text        NOT NULL,
    owner           text        NOT NULL,     -- session user_id, stringified
    visibility      text        NOT NULL DEFAULT 'private',
    allowed_groups  text[]      NOT NULL DEFAULT '{}',
    definition      jsonb       NOT NULL,     -- StudioAgentDefinition (schema_version 1)
    status          text        NOT NULL DEFAULT 'active',
    version         integer     NOT NULL DEFAULT 1,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ai_agents_visibility_chk CHECK (visibility IN ('private','tenant','groups')),
    CONSTRAINT ai_agents_status_chk     CHECK (status IN ('active','disabled')),
    CONSTRAINT ai_agents_name_chk       CHECK (name ~ '^[a-z0-9_-]{1,64}$'),
    CONSTRAINT ai_agents_tenant_chk     CHECK (tenant IS NULL OR tenant ~ '^[a-z0-9][a-z0-9_-]{0,62}$'),
    CONSTRAINT ai_agents_shared_needs_tenant_chk CHECK (tenant IS NOT NULL OR visibility = 'private'),
    CONSTRAINT ai_agents_definition_chk CHECK (jsonb_typeof(definition) = 'object'),
    CONSTRAINT ai_agents_tenant_name_key UNIQUE (tenant, name)
);
-- NULLs are distinct in a UNIQUE constraint; this closes the gap for non-tenant rows
-- without requiring PG15 "NULLS NOT DISTINCT".
CREATE UNIQUE INDEX IF NOT EXISTS ai_agents_global_name_uq ON navigator.ai_agents (name) WHERE tenant IS NULL;
CREATE INDEX IF NOT EXISTS ai_agents_tenant_owner_idx      ON navigator.ai_agents (tenant, owner);
CREATE INDEX IF NOT EXISTS ai_agents_tenant_visibility_idx ON navigator.ai_agents (tenant, visibility);
CREATE INDEX IF NOT EXISTS ai_agents_allowed_groups_gin    ON navigator.ai_agents USING gin (allowed_groups);

CREATE TABLE IF NOT EXISTS navigator.ai_agent_assets (
    agent_id      uuid        NOT NULL REFERENCES navigator.ai_agents(agent_id) ON DELETE CASCADE,
    kind          text        NOT NULL,
    name          text        NOT NULL,       -- relative path, e.g. 'role.md', 'faq.md', 'triage/SKILL.md'
    content       text        NULL,           -- v1: always set (text only)
    content_type  text        NOT NULL DEFAULT 'text/markdown',
    size          integer     NOT NULL,       -- octet_length(content) for text rows
    storage_uri   text        NULL,           -- reserved: phase-S3 binary documents (v1 never writes it)
    sha256        text        NOT NULL,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, kind, name),
    CONSTRAINT ai_agent_assets_kind_chk     CHECK (kind IN ('identity','kb','skills')),
    CONSTRAINT ai_agent_assets_body_chk     CHECK (content IS NOT NULL OR storage_uri IS NOT NULL),
    CONSTRAINT ai_agent_assets_hard_cap_chk CHECK (content IS NULL OR octet_length(content) <= 1048576),
    CONSTRAINT ai_agent_assets_size_chk     CHECK (size >= 0),
    CONSTRAINT ai_agent_assets_sha_chk      CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ai_agent_assets_name_chk     CHECK (name !~ '(^/|\.\.)')
);

CREATE TABLE IF NOT EXISTS navigator.ai_agent_tooling (
    agent_id     uuid        NOT NULL REFERENCES navigator.ai_agents(agent_id) ON DELETE CASCADE,
    kind         text        NOT NULL,
    slug         text        NOT NULL,        -- toolkit slug, or MCP server name
    position     integer     NOT NULL DEFAULT 0,
    config       jsonb       NOT NULL DEFAULT '{}'::jsonb,   -- secret-free spec dump (ToolkitSpec / AgentMCPServerSpec)
    secret_refs  jsonb       NOT NULL DEFAULT '{}'::jsonb,   -- {dotted.path: vault_name}; values never stored here
    vault_owner  text        NULL,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, kind, slug),
    CONSTRAINT ai_agent_tooling_kind_chk     CHECK (kind IN ('toolkit','mcp')),
    CONSTRAINT ai_agent_tooling_position_chk CHECK (position >= 0),
    CONSTRAINT ai_agent_tooling_config_chk   CHECK (jsonb_typeof(config) = 'object'),
    CONSTRAINT ai_agent_tooling_refs_chk     CHECK (jsonb_typeof(secret_refs) = 'object')
);

-- Version bump is enforced in the database so that no writer (Studio, a host backfill,
-- psql) can change a row without the other pods noticing (§2.6). Generic: reused by drafts.
CREATE OR REPLACE FUNCTION navigator.ai_studio_bump_version() RETURNS trigger AS $$
BEGIN
    NEW.version    := OLD.version + 1;
    NEW.updated_at := now();
    RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER ai_agents_bump_version_trg
    BEFORE UPDATE ON navigator.ai_agents
    FOR EACH ROW EXECUTE FUNCTION navigator.ai_studio_bump_version();

-- A child write touches the parent, which bumps its version through the trigger above.
-- When the parent itself is being deleted (ON DELETE CASCADE) the UPDATE matches no row.
CREATE OR REPLACE FUNCTION navigator.ai_agents_touch_parent() RETURNS trigger AS $$
BEGIN
    UPDATE navigator.ai_agents SET updated_at = now()
     WHERE agent_id = COALESCE(NEW.agent_id, OLD.agent_id);
    RETURN NULL;
END $$ LANGUAGE plpgsql;
CREATE OR REPLACE TRIGGER ai_agent_assets_touch_trg
    AFTER INSERT OR UPDATE OR DELETE ON navigator.ai_agent_assets
    FOR EACH ROW EXECUTE FUNCTION navigator.ai_agents_touch_parent();
CREATE OR REPLACE TRIGGER ai_agent_tooling_touch_trg
    AFTER INSERT OR UPDATE OR DELETE ON navigator.ai_agent_tooling
    FOR EACH ROW EXECUTE FUNCTION navigator.ai_agents_touch_parent();
-- @studio-ledger
INSERT INTO navigator.ai_studio_migrations (version, name, checksum)
VALUES (2, '0002_ai_agents', '11ec7724f035a4890fed91773efffcd15ed9bc8710680db65670897e3d193751')
ON CONFLICT (version) DO NOTHING;
