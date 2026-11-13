-- Source: FEAT-fold-legacy-llm-columns.sql; independently guard each scalar.
DO $migration$
DECLARE
    table_oid OID := to_regclass('{schema}.{bots_table}');
    source_column TEXT;
BEGIN
    FOREACH source_column IN ARRAY ARRAY['model_name', 'temperature', 'max_tokens', 'top_k', 'top_p']
    LOOP
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_attribute
            WHERE attrelid = table_oid AND attname = source_column AND NOT attisdropped
        ) THEN
            IF EXISTS (
                SELECT 1
                FROM {schema}.{bots_table}
                WHERE model_config IS NOT NULL AND jsonb_typeof(model_config) <> 'object'
            ) THEN
                RAISE EXCEPTION 'bots LLM fold requires object model_config';
            END IF;

            EXECUTE format(
                'UPDATE %s SET model_config = jsonb_set(COALESCE(model_config, ''{}''::JSONB), ARRAY[%L], '
                || 'to_jsonb(%I), TRUE) WHERE %I IS NOT NULL '
                || 'AND NOT (COALESCE(model_config, ''{}''::JSONB) ? %L)',
                table_oid::REGCLASS,
                source_column,
                source_column,
                source_column,
                source_column
            );
            EXECUTE format('ALTER TABLE %s DROP COLUMN %I', table_oid::REGCLASS, source_column);
        END IF;
    END LOOP;

    UPDATE {schema}.{bots_table}
    SET model_config = jsonb_set(model_config, '{model}', model_config->'model_name', TRUE)
    WHERE jsonb_typeof(model_config) = 'object'
      AND model_config ? 'model_name'
      AND NOT (model_config ? 'model');
END
$migration$;
