-- FEAT-884 postcondition: full BotModel-compatible baseline, independent of later language changes.
WITH target AS (
    SELECT to_regclass('{schema}.{bots_table}') AS table_oid
), expected_columns(column_name, type_name, requires_not_null, requires_default) AS (
    VALUES
        ('chatbot_id', 'uuid', TRUE, TRUE), ('name', 'character varying', TRUE, FALSE),
        ('description', 'text', FALSE, FALSE), ('avatar', 'text', FALSE, FALSE),
        ('enabled', 'boolean', TRUE, TRUE), ('timezone', 'character varying', FALSE, TRUE),
        ('role', 'character varying', FALSE, TRUE), ('goal', 'text', TRUE, TRUE),
        ('backstory', 'text', TRUE, TRUE), ('rationale', 'text', TRUE, TRUE),
        ('capabilities', 'text', FALSE, TRUE), ('system_prompt_template', 'text', FALSE, FALSE),
        ('human_prompt_template', 'text', FALSE, FALSE), ('pre_instructions', 'jsonb', FALSE, TRUE),
        ('prompt_config', 'jsonb', TRUE, TRUE), ('llm', 'character varying', FALSE, TRUE),
        ('model_config', 'jsonb', FALSE, TRUE), ('tools_enabled', 'boolean', FALSE, TRUE),
        ('auto_tool_detection', 'boolean', FALSE, TRUE), ('tool_threshold', 'double precision', FALSE, TRUE),
        ('tools', 'jsonb', FALSE, TRUE), ('toolkit_config', 'jsonb', FALSE, TRUE),
        ('mcp_servers', 'jsonb', FALSE, TRUE), ('operation_mode', 'character varying', FALSE, TRUE),
        ('use_vector', 'boolean', FALSE, TRUE), ('vector_store_config', 'jsonb', FALSE, TRUE),
        ('reranker_config', 'jsonb', FALSE, TRUE), ('parent_searcher_config', 'jsonb', FALSE, TRUE),
        ('context_search_limit', 'integer', FALSE, TRUE), ('context_score_threshold', 'double precision', FALSE, TRUE),
        ('memory_type', 'character varying', FALSE, TRUE), ('memory_config', 'jsonb', FALSE, TRUE),
        ('max_context_turns', 'integer', FALSE, TRUE), ('use_conversation_history', 'boolean', FALSE, TRUE),
        ('enable_suggestions', 'boolean', FALSE, TRUE), ('suggest_followups', 'boolean', FALSE, TRUE),
        ('suggestion_timeout_s', 'real', FALSE, TRUE), ('max_suggestions', 'integer', FALSE, TRUE),
        ('suggestion_model', 'character varying', FALSE, FALSE), ('permissions', 'jsonb', FALSE, TRUE),
        ('use_kb', 'boolean', FALSE, TRUE), ('kb', 'jsonb', FALSE, FALSE), ('custom_kbs', 'jsonb', FALSE, FALSE),
        ('bot_class', 'character varying', FALSE, FALSE), ('language', 'character varying', FALSE, FALSE),
        ('disclaimer', 'text', FALSE, FALSE), ('created_at', 'timestamp with time zone', FALSE, TRUE),
        ('created_by', 'integer', FALSE, FALSE), ('updated_at', 'timestamp with time zone', FALSE, TRUE)
), columns_ok AS (
    SELECT bool_and(
        attribute.attname IS NOT NULL
        AND format_type(attribute.atttypid, NULL) = expected_columns.type_name
        AND (NOT expected_columns.requires_not_null OR attribute.attnotnull)
        AND (NOT expected_columns.requires_default OR defaults.oid IS NOT NULL)
    ) AS ok
    FROM expected_columns
    CROSS JOIN target
    LEFT JOIN pg_catalog.pg_attribute AS attribute
        ON attribute.attrelid = target.table_oid
        AND attribute.attname = expected_columns.column_name
        AND NOT attribute.attisdropped
    LEFT JOIN pg_catalog.pg_attrdef AS defaults
        ON defaults.adrelid = attribute.attrelid AND defaults.adnum = attribute.attnum
), keys_ok AS (
    SELECT
        EXISTS (
            SELECT 1 FROM pg_catalog.pg_constraint AS constraint
            JOIN pg_catalog.pg_attribute AS attribute
                ON attribute.attrelid = constraint.conrelid AND attribute.attnum = constraint.conkey[1]
            CROSS JOIN target
            WHERE constraint.conrelid = target.table_oid AND constraint.contype = 'p' AND attribute.attname = 'chatbot_id'
        )
        AND EXISTS (
            SELECT 1 FROM pg_catalog.pg_constraint AS constraint
            JOIN pg_catalog.pg_attribute AS attribute
                ON attribute.attrelid = constraint.conrelid AND attribute.attnum = constraint.conkey[1]
            CROSS JOIN target
            WHERE constraint.conrelid = target.table_oid AND constraint.contype = 'u' AND attribute.attname = 'name'
        ) AS ok
), indexes_ok AS (
    SELECT bool_and(EXISTS (
        SELECT 1
        FROM pg_catalog.pg_index AS index
        JOIN pg_catalog.pg_class AS index_relation ON index_relation.oid = index.indexrelid
        JOIN pg_catalog.pg_am AS access_method ON access_method.oid = index_relation.relam
        JOIN pg_catalog.pg_attribute AS attribute
            ON attribute.attrelid = index.indrelid AND attribute.attnum = ANY(index.indkey)
        CROSS JOIN target
        WHERE index.indrelid = target.table_oid AND index.indisvalid
          AND attribute.attname = required.column_name AND access_method.amname = required.access_method
    )) AS ok
    FROM (VALUES
        ('name', 'btree'), ('enabled', 'btree'), ('operation_mode', 'btree'), ('tools_enabled', 'btree'),
        ('use_vector', 'btree'), ('created_at', 'btree'), ('llm', 'btree'), ('tools', 'gin'),
        ('permissions', 'gin'), ('model_config', 'gin'), ('reranker_config', 'gin'), ('parent_searcher_config', 'gin')
    ) AS required(column_name, access_method)
), trigger_ok AS (
    SELECT EXISTS (
        SELECT 1 FROM pg_catalog.pg_trigger AS trigger
        CROSS JOIN target
        WHERE trigger.tgrelid = target.table_oid AND NOT trigger.tgisinternal
    ) AS ok
)
SELECT COALESCE(columns_ok.ok, FALSE) AND keys_ok.ok AND indexes_ok.ok AND trigger_ok.ok
FROM columns_ok CROSS JOIN keys_ok CROSS JOIN indexes_ok CROSS JOIN trigger_ok;
