SELECT pg_advisory_xact_lock(4715391001);
CREATE TABLE IF NOT EXISTS navigator.ai_user_credentials (
    user_id     text        NOT NULL,
    name        text        NOT NULL,    -- vault name, e.g. toolkit_<slug>_studio-agent:<uuid>
    credential  text        NOT NULL,    -- encrypt_credential(secret_params, credential_context(user_id, name), keyring)
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, name)
);
-- @studio-ledger
INSERT INTO navigator.ai_studio_migrations (version, name, checksum)
VALUES (7, '0007_ai_user_credentials', '1c68ad8e9de4c618f7bfd369008f9c583282bd80d37bd415982bb7bd3cbeca03')
ON CONFLICT (version) DO NOTHING;
