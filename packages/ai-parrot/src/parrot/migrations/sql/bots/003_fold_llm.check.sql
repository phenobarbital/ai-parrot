-- FEAT-884 postcondition: legacy columns absent and model aliases are complete without overwriting explicit keys.
WITH target AS (
    SELECT to_regclass('{schema}.{bots_table}') AS table_oid
), sources_absent AS (
    SELECT NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_attribute AS attribute
        CROSS JOIN target
        WHERE attribute.attrelid = target.table_oid
          AND attribute.attname = ANY(ARRAY['model_name', 'temperature', 'max_tokens', 'top_k', 'top_p'])
          AND NOT attribute.attisdropped
    ) AS ok
), aliases_complete AS (
    SELECT NOT EXISTS (
        SELECT 1
        FROM {schema}.{bots_table}
        WHERE jsonb_typeof(model_config) = 'object'
          AND model_config ? 'model_name'
          AND NOT (model_config ? 'model')
    ) AS ok
)
SELECT sources_absent.ok AND aliases_complete.ok
FROM sources_absent CROSS JOIN aliases_complete;
