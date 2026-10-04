SELECT pg_advisory_xact_lock(4715391001);
CREATE TABLE IF NOT EXISTS navigator.ai_user_toolkit_overrides (
    user_id      text        NOT NULL,
    agent_ref    text        NOT NULL,   -- tooling ref (§2.5c): 'studio-agent:<uuid>' or a legacy bare name
    slug         text        NOT NULL,
    params       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    secret_refs  jsonb       NOT NULL DEFAULT '{}'::jsonb,
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, agent_ref, slug),
    CONSTRAINT ai_user_toolkit_overrides_params_chk CHECK (jsonb_typeof(params) = 'object'),
    CONSTRAINT ai_user_toolkit_overrides_refs_chk   CHECK (jsonb_typeof(secret_refs) = 'object')
);
CREATE INDEX IF NOT EXISTS ai_user_toolkit_overrides_agent_idx ON navigator.ai_user_toolkit_overrides (agent_ref);
-- @studio-ledger
INSERT INTO navigator.ai_studio_migrations (version, name, checksum)
VALUES (8, '0008_ai_user_toolkit_overrides', 'fe20c8ff3d59821d21cb26fd8169afc12f330819f5be67817d230d974039048a')
ON CONFLICT (version) DO NOTHING;
