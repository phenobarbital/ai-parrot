-- FEAT-884 postcondition: runtime UI surface tables, keys, defaults, and indexes.
SELECT
    to_regclass('navigator.ui_surfaces') IS NOT NULL
    AND to_regclass('navigator.ui_surface_shares') IS NOT NULL
    AND NOT EXISTS (
        SELECT 1
        FROM (VALUES
            ('surface_id', 'uuid'::regtype, true),
            ('kind', 'character varying'::regtype, true),
            ('title', 'text'::regtype, true),
            ('envelope', 'jsonb'::regtype, true),
            ('agent_id', 'character varying'::regtype, true),
            ('user_id', 'character varying'::regtype, true),
            ('recipe_params', 'jsonb'::regtype, true),
            ('tenant', 'character varying'::regtype, false),
            ('visibility', 'character varying'::regtype, true),
            ('allowed_groups', 'jsonb'::regtype, true),
            ('created_at', 'timestamp with time zone'::regtype, true),
            ('updated_at', 'timestamp with time zone'::regtype, true)
        ) AS required(column_name, type_id, not_null)
        LEFT JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = 'navigator.ui_surfaces'::regclass
         AND attribute.attname = required.column_name
         AND NOT attribute.attisdropped
        WHERE attribute.attnum IS NULL
           OR attribute.atttypid <> required.type_id
           OR attribute.attnotnull <> required.not_null
    )
    AND NOT EXISTS (
        SELECT 1
        FROM (VALUES
            ('token', 'text'::regtype, true),
            ('surface_id', 'uuid'::regtype, true),
            ('permissions', 'character varying'::regtype, true),
            ('revoked', 'boolean'::regtype, true),
            ('created_at', 'timestamp with time zone'::regtype, true)
        ) AS required(column_name, type_id, not_null)
        LEFT JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = 'navigator.ui_surface_shares'::regclass
         AND attribute.attname = required.column_name
         AND NOT attribute.attisdropped
        WHERE attribute.attnum IS NULL
           OR attribute.atttypid <> required.type_id
           OR attribute.attnotnull <> required.not_null
    )
    AND EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint constraint
        WHERE constraint.conrelid = 'navigator.ui_surfaces'::regclass AND constraint.contype = 'p'
    )
    AND EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint constraint
        WHERE constraint.conrelid = 'navigator.ui_surface_shares'::regclass
          AND constraint.contype = 'f' AND constraint.confdeltype = 'c'
    )
    AND (
        SELECT pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)
        FROM pg_catalog.pg_attrdef default_value
        JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = default_value.adrelid AND attribute.attnum = default_value.adnum
        WHERE default_value.adrelid = 'navigator.ui_surfaces'::regclass
          AND attribute.attname = 'recipe_params'
    ) LIKE '%{}%jsonb%'
    AND (
        SELECT pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)
        FROM pg_catalog.pg_attrdef default_value
        JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = default_value.adrelid AND attribute.attnum = default_value.adnum
        WHERE default_value.adrelid = 'navigator.ui_surfaces'::regclass
          AND attribute.attname = 'visibility'
    ) LIKE '%private%'
    AND (
        SELECT pg_catalog.pg_get_expr(default_value.adbin, default_value.adrelid)
        FROM pg_catalog.pg_attrdef default_value
        JOIN pg_catalog.pg_attribute attribute
          ON attribute.attrelid = default_value.adrelid AND attribute.attnum = default_value.adnum
        WHERE default_value.adrelid = 'navigator.ui_surfaces'::regclass
          AND attribute.attname = 'allowed_groups'
    ) LIKE '%[]%jsonb%'
    AND (
        SELECT count(*) FROM pg_catalog.pg_index index_definition
        JOIN pg_catalog.pg_class index_relation ON index_relation.oid = index_definition.indexrelid
        WHERE index_definition.indrelid = 'navigator.ui_surfaces'::regclass
          AND index_relation.relname IN (
              'ix_ui_surfaces_user', 'ix_ui_surfaces_user_kind', 'ix_ui_surfaces_tenant_visibility'
          )
    ) = 3
    AND (
        SELECT count(*) FROM pg_catalog.pg_index index_definition
        JOIN pg_catalog.pg_class index_relation ON index_relation.oid = index_definition.indexrelid
        WHERE index_definition.indrelid = 'navigator.ui_surface_shares'::regclass
          AND index_relation.relname IN ('ix_ui_surface_shares_surface', 'ix_ui_surface_shares_claimed_by')
    ) = 2;
