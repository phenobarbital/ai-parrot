-- Stored Jinja2 notification templates for the CommCenter bulk sender.
-- Templates are global (no user_id) by explicit spec decision — see
-- commcenter-notify.spec.md §8. created_by/updated_by are audit-only
-- columns, not ownership.

CREATE TABLE IF NOT EXISTS navigator.notification_templates (
    template_id       UUID NOT NULL DEFAULT uuid_generate_v4(),

    -- Identity — referenced by name from the sender endpoints.
    name              VARCHAR NOT NULL,

    -- Body — rendered once per batch (computed functions), then again
    -- per-recipient by NotifyWorker (record placeholders).
    template_string   TEXT NOT NULL,
    subject           VARCHAR,

    -- Default provider; overridable per request or per recipient row.
    provider          VARCHAR,
    description       TEXT,
    tags              VARCHAR[] DEFAULT '{}'::VARCHAR[],

    -- Inactive templates are rejected by /sender.
    is_active         BOOLEAN NOT NULL DEFAULT TRUE,

    -- Audit metadata — no ownership semantics (templates are global).
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    created_by        INTEGER,
    updated_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_by        INTEGER,

    PRIMARY KEY (template_id),
    CONSTRAINT unq_notification_templates_name UNIQUE (name)
);

CREATE INDEX IF NOT EXISTS idx_notification_templates_name
    ON navigator.notification_templates(name);
CREATE INDEX IF NOT EXISTS idx_notification_templates_is_active
    ON navigator.notification_templates(is_active);

CREATE OR REPLACE FUNCTION update_notification_templates_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS trigger_notification_templates_updated_at ON navigator.notification_templates;
CREATE TRIGGER trigger_notification_templates_updated_at
    BEFORE UPDATE ON navigator.notification_templates
    FOR EACH ROW
    EXECUTE FUNCTION update_notification_templates_updated_at();

COMMENT ON TABLE  navigator.notification_templates IS
    'Stored Jinja2 templates for the CommCenter bulk notification sender. Global (no user_id) — created_by/updated_by are audit-only.';
COMMENT ON COLUMN navigator.notification_templates.template_string IS
    'Jinja2 template body. Partially rendered once per batch (computed functions resolved), then rendered again per-recipient by NotifyWorker (record placeholders resolved).';
COMMENT ON COLUMN navigator.notification_templates.is_active IS
    'When FALSE, the template is rejected by POST /sender and POST /message.';
COMMENT ON COLUMN navigator.notification_templates.provider IS
    'Default provider for this template. Overridable per request (SenderRequest.provider) or per recipient row (RecipientIn.provider).';
