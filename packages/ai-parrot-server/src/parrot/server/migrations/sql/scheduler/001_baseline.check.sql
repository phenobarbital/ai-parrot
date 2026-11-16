-- FEAT-884 postcondition: complete scheduler row, compatible UUID default, primary key, and runtime indexes.
SELECT
    to_regclass('navigator.service_scheduler') IS NOT NULL
    AND NOT EXISTS (
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
    )
    AND EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint constraint_definition
        WHERE constraint_definition.conrelid = 'navigator.service_scheduler'::regclass
          AND constraint_definition.contype = 'p'
          AND pg_catalog.pg_get_constraintdef(constraint_definition.oid) = 'PRIMARY KEY (schedule_id)'
    )
    AND (
        SELECT pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)
        FROM pg_catalog.pg_attrdef default_value
        JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = default_value.adrelid AND attribute.attnum = default_value.adnum
        WHERE default_value.adrelid = 'navigator.service_scheduler'::regclass
          AND attribute.attname = 'schedule_id'
    ) ~ '(^|\\.)((gen_random_uuid)|(uuid_generate_v4))\\(\\)$'
    AND (
        SELECT pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)
        FROM pg_catalog.pg_attrdef default_value
        JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = default_value.adrelid AND attribute.attnum = default_value.adnum
        WHERE default_value.adrelid = 'navigator.service_scheduler'::regclass
          AND attribute.attname = 'enabled'
    ) = 'true'
    AND (
        SELECT pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)
        FROM pg_catalog.pg_attrdef default_value
        JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = default_value.adrelid AND attribute.attnum = default_value.adnum
        WHERE default_value.adrelid = 'navigator.service_scheduler'::regclass
          AND attribute.attname = 'run_count'
    ) = '0'
    AND NOT EXISTS (
        SELECT 1
        FROM (VALUES
            ('created_at', '%now()%'),
            ('updated_at', '%now()%'),
            ('last_callbacks', '%[]%jsonb%'),
            ('metadata', '%{}%jsonb%'),
            ('send_result', '%{}%jsonb%'),
            ('callbacks', '%[]%jsonb%')
        ) AS required(column_name, expected_pattern)
        LEFT JOIN (
            SELECT
                attribute.attname AS column_name,
                pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid) AS default_expression
            FROM pg_catalog.pg_attrdef default_value
            JOIN pg_catalog.pg_attribute attribute
              ON attribute.attrelid = default_value.adrelid AND attribute.attnum = default_value.adnum
            WHERE default_value.adrelid = 'navigator.service_scheduler'::regclass
        ) AS actual USING (column_name)
        WHERE actual.default_expression IS NULL
           OR actual.default_expression NOT LIKE required.expected_pattern
    )
    AND (
        SELECT pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)
        FROM pg_catalog.pg_attrdef default_value
        JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = default_value.adrelid AND attribute.attnum = default_value.adnum
        WHERE default_value.adrelid = 'navigator.service_scheduler'::regclass
          AND attribute.attname = 'consecutive_failures'
    ) = '0'
    AND (
        SELECT count(*)
        FROM pg_catalog.pg_index index_definition
        JOIN pg_catalog.pg_class index_relation ON index_relation.oid = index_definition.indexrelid
        WHERE index_definition.indrelid = 'navigator.service_scheduler'::regclass
          AND index_relation.relname IN ('idx_service_scheduler_enabled', 'idx_service_scheduler_target')
    ) = 2
    AND EXISTS (
        SELECT 1 FROM pg_catalog.pg_indexes
        WHERE schemaname = 'navigator'
          AND tablename = 'service_scheduler'
          AND indexname = 'idx_service_scheduler_enabled'
          AND indexdef LIKE '%(enabled)%'
    )
    AND EXISTS (
        SELECT 1 FROM pg_catalog.pg_indexes
        WHERE schemaname = 'navigator'
          AND tablename = 'service_scheduler'
          AND indexname = 'idx_service_scheduler_target'
          AND indexdef LIKE '%(target_kind, target_name)%'
    );
