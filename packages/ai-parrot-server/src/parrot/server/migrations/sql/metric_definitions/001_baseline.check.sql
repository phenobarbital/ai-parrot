-- FEAT-884 postcondition: metric definitions, namespace keys, visibility invariant, defaults, and indexes.
SELECT
    to_regclass('navigator.metric_definitions') IS NOT NULL
    AND NOT EXISTS (
        SELECT 1
        FROM (VALUES
            ('metric_id', 'character varying(63)', true),
            ('tenant', 'character varying(63)', false),
            ('name', 'text', true),
            ('owner', 'character varying', false),
            ('visibility', 'character varying(16)', true),
            ('allowed_groups', 'jsonb', true),
            ('global_only', 'boolean', true),
            ('program', 'character varying', false),
            ('definition', 'jsonb', true),
            ('version', 'integer', true),
            ('created_at', 'timestamp with time zone', true),
            ('updated_at', 'timestamp with time zone', true)
        ) AS required(column_name, type_name, not_null)
        LEFT JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = 'navigator.metric_definitions'::regclass
         AND attribute.attname = required.column_name
         AND NOT attribute.attisdropped
        WHERE attribute.attnum IS NULL
           OR pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) <> required.type_name
           OR attribute.attnotnull <> required.not_null
    )
    AND EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint constraint_definition
        WHERE constraint_definition.conrelid = 'navigator.metric_definitions'::regclass
          AND constraint_definition.contype = 'u'
          AND pg_catalog.pg_get_constraintdef(constraint_definition.oid) = 'UNIQUE (tenant, metric_id)'
    )
    AND EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint constraint_definition
        WHERE constraint_definition.conrelid = 'navigator.metric_definitions'::regclass
          AND constraint_definition.contype = 'c'
          AND pg_catalog.pg_get_constraintdef(constraint_definition.oid) LIKE '%tenant IS NOT NULL%visibility%tenant%'
    )
    AND (
        SELECT pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)
        FROM pg_catalog.pg_attrdef default_value
        JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = default_value.adrelid AND attribute.attnum = default_value.adnum
        WHERE default_value.adrelid = 'navigator.metric_definitions'::regclass
          AND attribute.attname = 'visibility'
    ) LIKE '%tenant%'
    AND (
        SELECT pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)
        FROM pg_catalog.pg_attrdef default_value
        JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = default_value.adrelid AND attribute.attnum = default_value.adnum
        WHERE default_value.adrelid = 'navigator.metric_definitions'::regclass
          AND attribute.attname = 'allowed_groups'
    ) LIKE '%[]%jsonb%'
    AND (
        SELECT pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)
        FROM pg_catalog.pg_attrdef default_value
        JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = default_value.adrelid AND attribute.attnum = default_value.adnum
        WHERE default_value.adrelid = 'navigator.metric_definitions'::regclass
          AND attribute.attname = 'global_only'
    ) = 'false'
    AND (
        SELECT pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)
        FROM pg_catalog.pg_attrdef default_value
        JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = default_value.adrelid AND attribute.attnum = default_value.adnum
        WHERE default_value.adrelid = 'navigator.metric_definitions'::regclass
          AND attribute.attname = 'version'
    ) = '1'
    AND NOT EXISTS (
        SELECT 1
        FROM (VALUES
            ('created_at', '%now()%'),
            ('updated_at', '%now()%')
        ) AS required(column_name, expected_pattern)
        LEFT JOIN (
            SELECT
                attribute.attname AS column_name,
                pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid) AS default_expression
            FROM pg_catalog.pg_attrdef default_value
            JOIN pg_catalog.pg_attribute attribute
              ON attribute.attrelid = default_value.adrelid AND attribute.attnum = default_value.adnum
            WHERE default_value.adrelid = 'navigator.metric_definitions'::regclass
        ) AS actual USING (column_name)
        WHERE actual.default_expression IS NULL
           OR actual.default_expression NOT LIKE required.expected_pattern
    )
    AND (
        SELECT count(*)
        FROM pg_catalog.pg_index index_definition
        JOIN pg_catalog.pg_class index_relation ON index_relation.oid = index_definition.indexrelid
        WHERE index_definition.indrelid = 'navigator.metric_definitions'::regclass
          AND index_relation.relname IN (
              'metric_definitions_global_uq',
              'metric_definitions_tenant_vis_idx',
              'metric_definitions_program_idx'
          )
    ) = 3
    AND EXISTS (
        SELECT 1
        FROM pg_catalog.pg_indexes
        WHERE schemaname = 'navigator'
          AND tablename = 'metric_definitions'
          AND indexname = 'metric_definitions_global_uq'
          AND indexdef LIKE '%UNIQUE%WHERE (tenant IS NULL)%'
    )
    AND EXISTS (
        SELECT 1 FROM pg_catalog.pg_indexes
        WHERE schemaname = 'navigator'
          AND tablename = 'metric_definitions'
          AND indexname = 'metric_definitions_tenant_vis_idx'
          AND indexdef LIKE '%(tenant, visibility)%'
    )
    AND EXISTS (
        SELECT 1 FROM pg_catalog.pg_indexes
        WHERE schemaname = 'navigator'
          AND tablename = 'metric_definitions'
          AND indexname = 'metric_definitions_program_idx'
          AND indexdef LIKE '%(program)%'
    );
