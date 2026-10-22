SELECT pg_advisory_xact_lock(4715391001);
CREATE TABLE IF NOT EXISTS navigator.ai_user_llm_keys (
    user_id      text        NOT NULL,
    provider     text        NOT NULL,
    api_key_enc  text        NOT NULL,   -- encrypt_credential({"api_key": …}, llm_key_context(user_id, provider), keyring)
    key_id       integer     NOT NULL,   -- keyring version that sealed it (rotation audit)
    masked       text        NOT NULL,   -- byok._mask() output, for GET without decrypt
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, provider)
);
-- @studio-ledger
INSERT INTO navigator.ai_studio_migrations (version, name, checksum)
VALUES (6, '0006_ai_user_llm_keys', '24830ce67a39063f74519199d298ae3b9ad256c2913ed63215ee72cd1f628123')
ON CONFLICT (version) DO NOTHING;
