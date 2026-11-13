-- Provenance: parrot.scheduler.models.ServiceSchedule
CREATE SCHEMA IF NOT EXISTS navigator;
CREATE TABLE IF NOT EXISTS navigator.service_scheduler (
    schedule_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_kind VARCHAR NOT NULL,
    target_name VARCHAR NOT NULL,
    target_id VARCHAR,
    tenant VARCHAR,
    prompt TEXT,
    method_name VARCHAR,
    schedule_type VARCHAR NOT NULL,
    schedule_config JSONB NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    created_by INTEGER,
    created_email VARCHAR,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    last_run TIMESTAMPTZ,
    next_run TIMESTAMPTZ,
    run_count INTEGER DEFAULT 0,
    last_status VARCHAR,
    last_error TEXT,
    last_error_at TIMESTAMPTZ,
    last_result TEXT,
    last_result_at TIMESTAMPTZ,
    consecutive_failures INTEGER DEFAULT 0,
    last_delivery_status VARCHAR,
    last_delivery_at TIMESTAMPTZ,
    last_callbacks JSONB DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    send_result JSONB DEFAULT '{}'::jsonb,
    callbacks JSONB DEFAULT '[]'::jsonb
);

ALTER TABLE navigator.service_scheduler
    ADD COLUMN IF NOT EXISTS schedule_id UUID DEFAULT gen_random_uuid();
ALTER TABLE navigator.service_scheduler ALTER COLUMN schedule_id SET NOT NULL;

DO $$
DECLARE
    required_column RECORD;
BEGIN
    FOR required_column IN
        SELECT *
        FROM (VALUES
            ('target_kind', 'VARCHAR'),
            ('target_name', 'VARCHAR'),
            ('schedule_type', 'VARCHAR'),
            ('schedule_config', 'JSONB')
        ) AS columns(column_name, type_name)
    LOOP
        IF NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_attribute attribute
            WHERE attribute.attrelid = 'navigator.service_scheduler'::regclass
              AND attribute.attname = required_column.column_name
              AND NOT attribute.attisdropped
        ) THEN
            IF EXISTS (SELECT 1 FROM navigator.service_scheduler) THEN
                RAISE EXCEPTION USING
                    ERRCODE = '42804',
                    MESSAGE = 'navigator.service_scheduler is missing required columns';
            END IF;
            EXECUTE format(
                'ALTER TABLE navigator.service_scheduler ADD COLUMN %I %s NOT NULL',
                required_column.column_name,
                required_column.type_name
            );
        END IF;
    END LOOP;
END $$;

ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS target_id VARCHAR;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS tenant VARCHAR;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS prompt TEXT;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS method_name VARCHAR;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS created_by INTEGER;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS created_email VARCHAR;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS last_run TIMESTAMPTZ;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS next_run TIMESTAMPTZ;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS run_count INTEGER DEFAULT 0;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS last_status VARCHAR;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMPTZ;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS last_result TEXT;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS last_result_at TIMESTAMPTZ;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER DEFAULT 0;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS last_delivery_status VARCHAR;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS last_delivery_at TIMESTAMPTZ;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS last_callbacks JSONB DEFAULT '[]'::jsonb;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS send_result JSONB DEFAULT '{}'::jsonb;
ALTER TABLE navigator.service_scheduler ADD COLUMN IF NOT EXISTS callbacks JSONB DEFAULT '[]'::jsonb;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM (VALUES
            ('schedule_id', 'uuid', true),
            ('target_kind', 'character varying', true),
            ('target_name', 'character varying', true),
            ('target_id', 'character varying', false),
            ('tenant', 'character varying', false),
            ('prompt', 'text', false),
            ('method_name', 'character varying', false),
            ('schedule_type', 'character varying', true),
            ('schedule_config', 'jsonb', true),
            ('enabled', 'boolean', false),
            ('created_by', 'integer', false),
            ('created_email', 'character varying', false),
            ('created_at', 'timestamp with time zone', false),
            ('updated_at', 'timestamp with time zone', false),
            ('last_run', 'timestamp with time zone', false),
            ('next_run', 'timestamp with time zone', false),
            ('run_count', 'integer', false),
            ('last_status', 'character varying', false),
            ('last_error', 'text', false),
            ('last_error_at', 'timestamp with time zone', false),
            ('last_result', 'text', false),
            ('last_result_at', 'timestamp with time zone', false),
            ('consecutive_failures', 'integer', false),
            ('last_delivery_status', 'character varying', false),
            ('last_delivery_at', 'timestamp with time zone', false),
            ('last_callbacks', 'jsonb', false),
            ('metadata', 'jsonb', false),
            ('send_result', 'jsonb', false),
            ('callbacks', 'jsonb', false)
        ) AS required(column_name, type_name, not_null)
        LEFT JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = 'navigator.service_scheduler'::regclass
         AND attribute.attname = required.column_name
         AND NOT attribute.attisdropped
        WHERE attribute.attnum IS NULL
           OR pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) <> required.type_name
           OR attribute.attnotnull <> required.not_null
    ) THEN
        RAISE EXCEPTION USING
            ERRCODE = '42804',
            MESSAGE = 'navigator.service_scheduler has incompatible columns';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint constraint_definition
        WHERE constraint_definition.conrelid = 'navigator.service_scheduler'::regclass
          AND constraint_definition.contype = 'p'
          AND pg_catalog.pg_get_constraintdef(constraint_definition.oid) = 'PRIMARY KEY (schedule_id)'
    ) THEN
        ALTER TABLE navigator.service_scheduler
            ADD CONSTRAINT service_scheduler_pkey PRIMARY KEY (schedule_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_service_scheduler_enabled
    ON navigator.service_scheduler (enabled);
CREATE INDEX IF NOT EXISTS idx_service_scheduler_target
    ON navigator.service_scheduler (target_kind, target_name);
