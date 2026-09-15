-- FEAT-459 / TASK-3165: versioned tenant-scoped snippet store.
-- Run once per physical Postgres schema, same convention as
-- 001-007 (see migrations/README.md). Idempotent via IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS form_snippets (
    id              BIGSERIAL PRIMARY KEY,
    tenant          TEXT NOT NULL,
    handler_ref     TEXT NOT NULL,
    event           TEXT NOT NULL,
    version         INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'published', 'revoked')),
    manifest        JSONB NOT NULL,
    python_source   TEXT NOT NULL,
    python_sha256   TEXT NOT NULL,
    client_source   TEXT,
    client_sha256   TEXT,
    approved_by     TEXT,
    approved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One row per (tenant, handler_ref, version) — republishing INSERTS a
    -- new version row rather than mutating history (audit trail, spec §7
    -- "Two audit trails" risk).
    UNIQUE (tenant, handler_ref, version)
);

-- Fast path for resolve_current(): "the currently published row for this
-- (tenant, handler_ref)". Partial index — only PUBLISHED rows matter here.
CREATE INDEX IF NOT EXISTS ix_form_snippets_published_lookup
    ON form_snippets (tenant, handler_ref)
    WHERE status = 'published';
