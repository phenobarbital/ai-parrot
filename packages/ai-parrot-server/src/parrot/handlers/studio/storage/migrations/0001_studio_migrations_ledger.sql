SELECT pg_advisory_xact_lock(4715391001);   -- STUDIO_MIGRATION_LOCK_KEY
CREATE SCHEMA IF NOT EXISTS navigator;
CREATE TABLE IF NOT EXISTS navigator.ai_studio_migrations (
    version     integer     PRIMARY KEY,
    name        text        NOT NULL,
    checksum    text        NOT NULL,          -- sha256 hex of the file BODY (§2.12), never of the trailer
    applied_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ai_studio_migrations_version_chk  CHECK (version > 0),
    CONSTRAINT ai_studio_migrations_checksum_chk CHECK (checksum ~ '^[0-9a-f]{64}$')
);
-- @studio-ledger
INSERT INTO navigator.ai_studio_migrations (version, name, checksum)
VALUES (1, '0001_studio_migrations_ledger', '45308b78c159fe5ccb6c2874f0f51eb858f2db3283843b341f6c52e75a202282')
ON CONFLICT (version) DO NOTHING;
