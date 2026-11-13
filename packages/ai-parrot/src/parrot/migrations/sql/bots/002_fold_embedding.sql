-- Source: FEAT-fold-embedding-model-into-vector-store-config.sql (bots only).
DO $migration$
DECLARE
    table_oid OID := to_regclass('{schema}.{bots_table}');
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_attribute
        WHERE attrelid = table_oid AND attname = 'embedding_model' AND NOT attisdropped
    ) THEN
        IF EXISTS (
            SELECT 1
            FROM "{schema}"."{bots_table}"
            WHERE embedding_model IS NOT NULL
              AND jsonb_typeof(COALESCE(vector_store_config, '{}'::JSONB)) <> 'object'
        ) THEN
            RAISE EXCEPTION 'bots embedding fold requires object vector_store_config';
        END IF;

        UPDATE "{schema}"."{bots_table}"
        SET vector_store_config = jsonb_set(
            COALESCE(vector_store_config, '{}'::JSONB),
            '{embedding_model}',
            embedding_model,
            TRUE
        )
        WHERE embedding_model IS NOT NULL
          AND NOT (COALESCE(vector_store_config, '{}'::JSONB) ? 'embedding_model');

        ALTER TABLE "{schema}"."{bots_table}" DROP COLUMN embedding_model;
    END IF;

    UPDATE "{schema}"."{bots_table}"
    SET vector_store_config = jsonb_set(
        vector_store_config #- '{embedding_model,model}',
        '{embedding_model,model_name}',
        vector_store_config #> '{embedding_model,model}',
        TRUE
    )
    WHERE jsonb_typeof(vector_store_config->'embedding_model') = 'object'
      AND (vector_store_config->'embedding_model') ? 'model'
      AND NOT ((vector_store_config->'embedding_model') ? 'model_name');
END
$migration$;
