-- Flat tracking table for CommCenter send batches. One row per recipient;
-- batch_id is repeated across every row belonging to the same batch. There
-- is intentionally NO separate "batches" header table — batch-level totals
-- are obtained by aggregating over this table (spec §3 Module 2).

CREATE TABLE IF NOT EXISTS navigator.notification_batch_recipients (
    id                  UUID NOT NULL DEFAULT uuid_generate_v4(),

    -- Repeated across every row of the same batch. Indexed for aggregation.
    batch_id            UUID NOT NULL,
    row_number          INTEGER,

    -- Resolved per row (global default overridable per recipient).
    provider            VARCHAR NOT NULL,
    recipient_name      VARCHAR,
    recipient_address   VARCHAR,

    -- Duplicate-delivery containment state machine (spec §2):
    --   created -> pending -> (set publishing, THEN xadd) -> publishing
    --     -> xadd returns entry id -> queued (terminal, never retried)
    --   pending -- validation failed --> skipped (terminal, never retried)
    --   publishing -- xadd raised --> publish_failed (safe to retry)
    status              VARCHAR NOT NULL
                        CHECK (status IN ('pending', 'publishing', 'queued',
                                          'skipped', 'publish_failed')),
    reason              TEXT,

    -- Redis stream entry id returned by xadd; set together with
    -- published_at only once xadd has actually returned.
    message_id          VARCHAR,
    published_at        TIMESTAMPTZ,
    attempts            INTEGER NOT NULL DEFAULT 0,

    template_ref        VARCHAR,
    subject             VARCHAR,

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    created_by          INTEGER,
    updated_at          TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS idx_notification_batch_recipients_batch_id
    ON navigator.notification_batch_recipients(batch_id);
CREATE INDEX IF NOT EXISTS idx_notification_batch_recipients_batch_status
    ON navigator.notification_batch_recipients(batch_id, status);

CREATE OR REPLACE FUNCTION update_notification_batch_recipients_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS trigger_notification_batch_recipients_updated_at ON navigator.notification_batch_recipients;
CREATE TRIGGER trigger_notification_batch_recipients_updated_at
    BEFORE UPDATE ON navigator.notification_batch_recipients
    FOR EACH ROW
    EXECUTE FUNCTION update_notification_batch_recipients_updated_at();

COMMENT ON TABLE  navigator.notification_batch_recipients IS
    'Flat per-recipient tracking table for CommCenter send batches. batch_id repeats per row; there is no separate batches header table, totals come from aggregation.';
COMMENT ON COLUMN navigator.notification_batch_recipients.status IS
    'State machine: pending -> publishing (written immediately before xadd) -> queued (terminal) on success, or publish_failed (retryable) on xadd exception. skipped is terminal and set when validation fails before any publish attempt.';
COMMENT ON COLUMN navigator.notification_batch_recipients.published_at IS
    'Set only once xadd has returned successfully. Together with status=publishing, narrows retry duplicate-delivery risk to rows caught mid-xadd (the retry marker).';
COMMENT ON COLUMN navigator.notification_batch_recipients.message_id IS
    'Redis stream entry id returned by NotifyClient.stream() (xadd). NULL until the row reaches status=queued.';
