-- FEAT-884 postcondition: default-schema recipe columns, defaults, composite identity, and owner index.
SELECT
    to_regclass('navigator.infographic_recipes') IS NOT NULL
    AND NOT EXISTS (
        SELECT 1
        FROM (VALUES
            ('name', 'character varying', true),
            ('owner', 'character varying', true),
            ('schema_version', 'integer', true),
            ('title', 'text', false),
            ('description', 'text', false),
            ('recipe', 'jsonb', true),
            ('created_at', 'timestamp with time zone', true),
            ('updated_at', 'timestamp with time zone', true)
        ) AS required(column_name, type_name, not_null)
        LEFT JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = 'navigator.infographic_recipes'::regclass
         AND attribute.attname = required.column_name
         AND NOT attribute.attisdropped
        WHERE attribute.attnum IS NULL
           OR pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) <> required.type_name
           OR attribute.attnotnull <> required.not_null
    )
    AND EXISTS (
        SELECT 1
        FROM pg_catalog.pg_constraint constraint_definition
        WHERE constraint_definition.conrelid = 'navigator.infographic_recipes'::regclass
          AND constraint_definition.contype = 'p'
          AND pg_catalog.pg_get_constraintdef(constraint_definition.oid) = 'PRIMARY KEY (name, owner)'
    )
    AND (
        SELECT pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)
        FROM pg_catalog.pg_attrdef default_value
        JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = default_value.adrelid AND attribute.attnum = default_value.adnum
        WHERE default_value.adrelid = 'navigator.infographic_recipes'::regclass
          AND attribute.attname = 'owner'
    ) = ''''::character varying'
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
            WHERE default_value.adrelid = 'navigator.infographic_recipes'::regclass
        ) AS actual USING (column_name)
        WHERE actual.default_expression IS NULL
           OR actual.default_expression NOT LIKE required.expected_pattern
    )
    AND EXISTS (
        SELECT 1
        FROM pg_catalog.pg_index index_definition
        JOIN pg_catalog.pg_class index_relation ON index_relation.oid = index_definition.indexrelid
        WHERE index_definition.indrelid = 'navigator.infographic_recipes'::regclass
          AND index_relation.relname = 'ix_infographic_recipes_owner'
          AND pg_catalog.pg_get_indexdef(index_definition.indexrelid) LIKE '%(owner)%'
    );
