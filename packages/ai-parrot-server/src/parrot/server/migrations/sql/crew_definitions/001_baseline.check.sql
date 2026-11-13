-- FEAT-884 postcondition: runtime crew definition rows, identity keys, and tombstones.
SELECT
    to_regclass('navigator.crew_definitions') IS NOT NULL
    AND NOT EXISTS (
        SELECT 1
        FROM (VALUES
            ('tenant', 'text'::regtype, true),
            ('name', 'text'::regtype, true),
            ('crew_id', 'text'::regtype, true),
            ('description', 'text'::regtype, false),
            ('execution_mode', 'character varying'::regtype, false),
            ('definition', 'jsonb'::regtype, true),
            ('created_at', 'timestamp with time zone'::regtype, true),
            ('updated_at', 'timestamp with time zone'::regtype, true),
            ('deleted_at', 'timestamp with time zone'::regtype, false)
        ) AS required(column_name, type_id, not_null)
        LEFT JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = 'navigator.crew_definitions'::regclass
         AND attribute.attname = required.column_name
         AND NOT attribute.attisdropped
        WHERE attribute.attnum IS NULL
           OR attribute.atttypid <> required.type_id
           OR attribute.attnotnull <> required.not_null
    )
    AND EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint constraint
        WHERE constraint.conrelid = 'navigator.crew_definitions'::regclass
          AND constraint.contype = 'p'
          AND pg_catalog.pg_get_constraintdef(constraint.oid) = 'PRIMARY KEY (tenant, name)'
    )
    AND EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint constraint
        WHERE constraint.conrelid = 'navigator.crew_definitions'::regclass
          AND constraint.contype = 'u'
          AND pg_catalog.pg_get_constraintdef(constraint.oid) = 'UNIQUE (tenant, crew_id)'
    )
    AND (
        SELECT pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)
        FROM pg_catalog.pg_attrdef default_value
        JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = default_value.adrelid AND attribute.attnum = default_value.adnum
        WHERE default_value.adrelid = 'navigator.crew_definitions'::regclass
          AND attribute.attname = 'tenant'
    ) LIKE '%global%';
