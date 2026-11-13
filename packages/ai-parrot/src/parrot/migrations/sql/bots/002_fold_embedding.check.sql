-- FEAT-884 postcondition: source absent and normalized destination invariant; explicit JSON null keys win.
WITH target AS (
    SELECT to_regclass('{schema}.{bots_table}') AS table_oid
), source_absent AS (
    SELECT NOT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_attribute AS attribute
        CROSS JOIN target
        WHERE attribute.attrelid = target.table_oid
          AND attribute.attname = 'embedding_model'
          AND NOT attribute.attisdropped
    ) AS ok
), destinations_normalized AS (
    SELECT NOT EXISTS (
        SELECT 1
        FROM "{schema}"."{bots_table}"
        WHERE jsonb_typeof(vector_store_config->'embedding_model') = 'object'
          AND (vector_store_config->'embedding_model') ? 'model'
          AND NOT ((vector_store_config->'embedding_model') ? 'model_name')
    ) AS ok
)
SELECT source_absent.ok AND destinations_normalized.ok
FROM source_absent CROSS JOIN destinations_normalized;
