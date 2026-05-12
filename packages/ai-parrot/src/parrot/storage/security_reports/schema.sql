-- parrot/storage/security_reports/schema.sql
-- Cross-session security report catalog — Postgres DDL
--
-- Applied out-of-band by ops (no migration framework in this project).
-- Also executed via PostgresS3SecurityReportStore.bootstrap_schema() for
-- local dev / first-run convenience. All statements are idempotent.
--
-- Style follows parrot/security/security_events.sql (finding F016).
-- Column names mirror ReportRef Pydantic field names one-to-one.

CREATE TABLE IF NOT EXISTS security_reports (
    report_id           UUID            PRIMARY KEY,
    report_kind         TEXT            NOT NULL,
    scanner             TEXT            NOT NULL,
    framework           TEXT,
    provider            TEXT            NOT NULL,
    scope               JSONB           NOT NULL DEFAULT '{}'::jsonb,
    severity_summary    JSONB           NOT NULL,
    top_findings        JSONB           NOT NULL DEFAULT '[]'::jsonb,
    uri                 TEXT            NOT NULL,
    content_type        TEXT            NOT NULL DEFAULT 'application/json',
    content_bytes       BIGINT,
    produced_at         TIMESTAMPTZ     NOT NULL,
    produced_by         TEXT            NOT NULL,
    parser_version      TEXT            NOT NULL,
    retention_class     TEXT            NOT NULL DEFAULT 'compliance',
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now()
);

-- Primary query axis: scanner + framework + recency
CREATE INDEX IF NOT EXISTS idx_security_reports_scanner_framework_produced
    ON security_reports (scanner, framework, produced_at DESC);

-- Summary / kind queries: fetch only weekly or monthly summaries
CREATE INDEX IF NOT EXISTS idx_security_reports_kind_produced
    ON security_reports (report_kind, produced_at DESC);

-- JSONB containment for scope_match filter (account_id, region, target, etc.)
CREATE INDEX IF NOT EXISTS idx_security_reports_scope_gin
    ON security_reports USING GIN (scope);
