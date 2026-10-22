-- Legacy Python drafts (non-tenant only). Create-if-missing, FEAT-467 columns
-- (models/studio_drafts.py docstring), gen_random_uuid() default; no column changes.
SELECT pg_advisory_xact_lock(4715391001);
CREATE TABLE IF NOT EXISTS navigator.studio_drafts (
    draft_id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    name              varchar     NOT NULL UNIQUE,
    file_path         varchar     NOT NULL,
    status            varchar     NOT NULL DEFAULT 'draft',
    validation_report jsonb       DEFAULT '{}'::jsonb,
    base_class        varchar,
    owner_user_id     varchar     NOT NULL,
    created_at        timestamptz DEFAULT now(),
    updated_at        timestamptz DEFAULT now(),
    activated_at      timestamptz
);
CREATE INDEX IF NOT EXISTS idx_studio_drafts_status ON navigator.studio_drafts (status);
CREATE INDEX IF NOT EXISTS idx_studio_drafts_owner  ON navigator.studio_drafts (owner_user_id);
-- @studio-ledger
INSERT INTO navigator.ai_studio_migrations (version, name, checksum)
VALUES (5, '0005_studio_drafts_baseline', '2b2d6029d6a52be72b0d296e407b1910b2a2a81ed3e45d5e290e820b0508b3f2')
ON CONFLICT (version) DO NOTHING;
