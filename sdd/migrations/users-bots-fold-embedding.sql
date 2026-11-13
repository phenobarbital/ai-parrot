-- MANUAL: users_bots embedding fold; not part of any packaged migration set.
--
-- Run this only after taking a backup and confirming that navigator.users_bots
-- is the intended legacy table. Missing relations or source columns are a
-- no-op. Existing vector_config.embedding_model keys, including JSON null,
-- are explicit operator values and always win over the legacy column.
DO $migration$
DECLARE
    table_oid OID := to_regclass('navigator.users_bots');
BEGIN
    IF table_oid IS NOT NULL
       AND EXISTS (
           SELECT 1 FROM pg_catalog.pg_attribute
           WHERE attrelid = table_oid AND attname = 'embedding_model' AND NOT attisdropped
       )
       AND EXISTS (
           SELECT 1 FROM pg_catalog.pg_attribute
           WHERE attrelid = table_oid AND attname = 'vector_config' AND NOT attisdropped
       ) THEN
        IF EXISTS (
            SELECT 1
            FROM navigator.users_bots
            WHERE embedding_model IS NOT NULL
              AND jsonb_typeof(COALESCE(vector_config, '{}'::JSONB)) <> 'object'
        ) THEN
            RAISE EXCEPTION 'users_bots embedding fold requires object vector_config';
        END IF;

        UPDATE navigator.users_bots
        SET vector_config = jsonb_set(
            COALESCE(vector_config, '{}'::JSONB),
            '{embedding_model}',
            embedding_model,
            TRUE
        )
        WHERE embedding_model IS NOT NULL
          AND NOT (COALESCE(vector_config, '{}'::JSONB) ? 'embedding_model');

        UPDATE navigator.users_bots
        SET vector_config = jsonb_set(
            vector_config #- '{embedding_model,model}',
            '{embedding_model,model_name}',
            vector_config #> '{embedding_model,model}',
            TRUE
        )
        WHERE jsonb_typeof(vector_config->'embedding_model') = 'object'
          AND (vector_config->'embedding_model') ? 'model'
          AND NOT ((vector_config->'embedding_model') ? 'model_name');

        ALTER TABLE navigator.users_bots DROP COLUMN embedding_model;
    END IF;
END
$migration$;
