-- Provenance: BotModel documented DDL and historical additive scripts.
CREATE TABLE IF NOT EXISTS {schema}.{bots_table} (
    chatbot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR NOT NULL,
    description TEXT,
    avatar TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    timezone VARCHAR(75) DEFAULT 'UTC',
    role VARCHAR DEFAULT 'AI Assistant',
    goal TEXT NOT NULL DEFAULT 'Help users accomplish their tasks effectively.',
    backstory TEXT NOT NULL DEFAULT 'I am an AI assistant created to help users with various tasks.',
    rationale TEXT NOT NULL DEFAULT 'I maintain a professional tone and provide accurate, helpful information.',
    capabilities TEXT DEFAULT 'I can engage in conversation, answer questions, and use tools when needed.',
    system_prompt_template TEXT,
    human_prompt_template TEXT,
    pre_instructions JSONB DEFAULT '[]'::JSONB,
    prompt_config JSONB NOT NULL DEFAULT '{}'::JSONB,
    llm VARCHAR DEFAULT 'google',
    model_config JSONB DEFAULT '{}'::JSONB,
    tools_enabled BOOLEAN DEFAULT TRUE,
    auto_tool_detection BOOLEAN DEFAULT TRUE,
    tool_threshold DOUBLE PRECISION DEFAULT 0.7,
    tools JSONB DEFAULT '[]'::JSONB,
    toolkit_config JSONB DEFAULT '{}'::JSONB,
    mcp_servers JSONB DEFAULT '[]'::JSONB,
    operation_mode VARCHAR DEFAULT 'adaptive',
    use_vector BOOLEAN DEFAULT FALSE,
    vector_store_config JSONB DEFAULT '{}'::JSONB,
    reranker_config JSONB DEFAULT '{}'::JSONB,
    parent_searcher_config JSONB DEFAULT '{}'::JSONB,
    context_search_limit INTEGER DEFAULT 10,
    context_score_threshold DOUBLE PRECISION DEFAULT 0.7,
    memory_type VARCHAR DEFAULT 'memory',
    memory_config JSONB DEFAULT '{}'::JSONB,
    max_context_turns INTEGER DEFAULT 5,
    use_conversation_history BOOLEAN DEFAULT TRUE,
    enable_suggestions BOOLEAN DEFAULT FALSE,
    suggest_followups BOOLEAN DEFAULT FALSE,
    suggestion_timeout_s REAL DEFAULT 4.0,
    max_suggestions INTEGER DEFAULT 6,
    suggestion_model VARCHAR,
    permissions JSONB DEFAULT '{}'::JSONB,
    use_kb BOOLEAN DEFAULT FALSE,
    kb JSONB,
    custom_kbs JSONB,
    bot_class VARCHAR,
    language VARCHAR(10),
    disclaimer TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by INTEGER,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

DO $baseline$
DECLARE
    table_oid OID := to_regclass('{schema}.{bots_table}');
    actual_type TEXT;
    expected RECORD;
    has_rows BOOLEAN;
BEGIN
    IF table_oid IS NULL THEN
        RAISE EXCEPTION 'bots migration precondition failed: configured table is unavailable';
    END IF;

    EXECUTE format('SELECT EXISTS (SELECT 1 FROM %s LIMIT 1)', table_oid::REGCLASS) INTO has_rows;
    IF has_rows
       AND (NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_attribute
                WHERE attrelid = table_oid AND attname = 'chatbot_id' AND NOT attisdropped
            )
            OR NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_attribute
                WHERE attrelid = table_oid AND attname = 'name' AND NOT attisdropped
            )) THEN
        RAISE EXCEPTION 'bots migration precondition failed: nonempty table lacks required identity';
    END IF;

    FOR expected IN
        SELECT * FROM (VALUES
            ('chatbot_id', 'uuid'), ('name', 'character varying'), ('description', 'text'),
            ('avatar', 'text'), ('enabled', 'boolean'), ('timezone', 'character varying'),
            ('role', 'character varying'), ('goal', 'text'), ('backstory', 'text'),
            ('rationale', 'text'), ('capabilities', 'text'), ('system_prompt_template', 'text'),
            ('human_prompt_template', 'text'), ('pre_instructions', 'jsonb'), ('prompt_config', 'jsonb'),
            ('llm', 'character varying'), ('model_config', 'jsonb'), ('tools_enabled', 'boolean'),
            ('auto_tool_detection', 'boolean'), ('tool_threshold', 'double precision'), ('tools', 'jsonb'),
            ('toolkit_config', 'jsonb'), ('mcp_servers', 'jsonb'), ('operation_mode', 'character varying'),
            ('use_vector', 'boolean'), ('vector_store_config', 'jsonb'), ('reranker_config', 'jsonb'),
            ('parent_searcher_config', 'jsonb'), ('context_search_limit', 'integer'),
            ('context_score_threshold', 'double precision'), ('memory_type', 'character varying'),
            ('memory_config', 'jsonb'), ('max_context_turns', 'integer'),
            ('use_conversation_history', 'boolean'), ('enable_suggestions', 'boolean'),
            ('suggest_followups', 'boolean'), ('suggestion_timeout_s', 'real'), ('max_suggestions', 'integer'),
            ('suggestion_model', 'character varying'), ('permissions', 'jsonb'), ('use_kb', 'boolean'),
            ('kb', 'jsonb'), ('custom_kbs', 'jsonb'), ('bot_class', 'character varying'),
            ('language', 'character varying'), ('disclaimer', 'text'), ('created_at', 'timestamp with time zone'),
            ('created_by', 'integer'), ('updated_at', 'timestamp with time zone')
        ) AS columns(column_name, type_name)
    LOOP
        SELECT format_type(attribute.atttypid, NULL) INTO actual_type
        FROM pg_catalog.pg_attribute AS attribute
        WHERE attribute.attrelid = table_oid
          AND attribute.attname = expected.column_name
          AND NOT attribute.attisdropped;
        IF actual_type IS NOT NULL AND actual_type <> expected.type_name THEN
            RAISE EXCEPTION 'bots migration precondition failed: column % has incompatible type', expected.column_name;
        END IF;
    END LOOP;
END;
$baseline$;

ALTER TABLE {schema}.{bots_table}
    ADD COLUMN IF NOT EXISTS chatbot_id UUID DEFAULT gen_random_uuid(),
    ADD COLUMN IF NOT EXISTS name VARCHAR NOT NULL,
    ADD COLUMN IF NOT EXISTS description TEXT,
    ADD COLUMN IF NOT EXISTS avatar TEXT,
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS timezone VARCHAR(75) DEFAULT 'UTC',
    ADD COLUMN IF NOT EXISTS role VARCHAR DEFAULT 'AI Assistant',
    ADD COLUMN IF NOT EXISTS goal TEXT NOT NULL DEFAULT 'Help users accomplish their tasks effectively.',
    ADD COLUMN IF NOT EXISTS backstory TEXT NOT NULL DEFAULT 'I am an AI assistant created to help users with various tasks.',
    ADD COLUMN IF NOT EXISTS rationale TEXT NOT NULL DEFAULT 'I maintain a professional tone and provide accurate, helpful information.',
    ADD COLUMN IF NOT EXISTS capabilities TEXT DEFAULT 'I can engage in conversation, answer questions, and use tools when needed.',
    ADD COLUMN IF NOT EXISTS system_prompt_template TEXT,
    ADD COLUMN IF NOT EXISTS human_prompt_template TEXT,
    ADD COLUMN IF NOT EXISTS pre_instructions JSONB DEFAULT '[]'::JSONB,
    ADD COLUMN IF NOT EXISTS prompt_config JSONB NOT NULL DEFAULT '{}'::JSONB,
    ADD COLUMN IF NOT EXISTS llm VARCHAR DEFAULT 'google',
    ADD COLUMN IF NOT EXISTS model_config JSONB DEFAULT '{}'::JSONB,
    ADD COLUMN IF NOT EXISTS tools_enabled BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS auto_tool_detection BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS tool_threshold DOUBLE PRECISION DEFAULT 0.7,
    ADD COLUMN IF NOT EXISTS tools JSONB DEFAULT '[]'::JSONB,
    ADD COLUMN IF NOT EXISTS toolkit_config JSONB DEFAULT '{}'::JSONB,
    ADD COLUMN IF NOT EXISTS mcp_servers JSONB DEFAULT '[]'::JSONB,
    ADD COLUMN IF NOT EXISTS operation_mode VARCHAR DEFAULT 'adaptive',
    ADD COLUMN IF NOT EXISTS use_vector BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS vector_store_config JSONB DEFAULT '{}'::JSONB,
    ADD COLUMN IF NOT EXISTS reranker_config JSONB DEFAULT '{}'::JSONB,
    ADD COLUMN IF NOT EXISTS parent_searcher_config JSONB DEFAULT '{}'::JSONB,
    ADD COLUMN IF NOT EXISTS context_search_limit INTEGER DEFAULT 10,
    ADD COLUMN IF NOT EXISTS context_score_threshold DOUBLE PRECISION DEFAULT 0.7,
    ADD COLUMN IF NOT EXISTS memory_type VARCHAR DEFAULT 'memory',
    ADD COLUMN IF NOT EXISTS memory_config JSONB DEFAULT '{}'::JSONB,
    ADD COLUMN IF NOT EXISTS max_context_turns INTEGER DEFAULT 5,
    ADD COLUMN IF NOT EXISTS use_conversation_history BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS enable_suggestions BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS suggest_followups BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS suggestion_timeout_s REAL DEFAULT 4.0,
    ADD COLUMN IF NOT EXISTS max_suggestions INTEGER DEFAULT 6,
    ADD COLUMN IF NOT EXISTS suggestion_model VARCHAR,
    ADD COLUMN IF NOT EXISTS permissions JSONB DEFAULT '{}'::JSONB,
    ADD COLUMN IF NOT EXISTS use_kb BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS kb JSONB,
    ADD COLUMN IF NOT EXISTS custom_kbs JSONB,
    ADD COLUMN IF NOT EXISTS bot_class VARCHAR,
    ADD COLUMN IF NOT EXISTS language VARCHAR(10),
    ADD COLUMN IF NOT EXISTS disclaimer TEXT,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS created_by INTEGER,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

DO $baseline$
DECLARE
    table_oid OID := to_regclass('{schema}.{bots_table}');
    schema_name TEXT;
    table_name TEXT;
    table_ref TEXT;
    name_attribute SMALLINT;
    id_attribute SMALLINT;
    object_name TEXT;
    constraint_expression TEXT;
BEGIN
    SELECT namespace.nspname, relation.relname INTO schema_name, table_name
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE relation.oid = table_oid;
    table_ref := format('%I.%I', schema_name, table_name);
    SELECT attnum INTO name_attribute FROM pg_catalog.pg_attribute
    WHERE attrelid = table_oid AND attname = 'name' AND NOT attisdropped;
    SELECT attnum INTO id_attribute FROM pg_catalog.pg_attribute
    WHERE attrelid = table_oid AND attname = 'chatbot_id' AND NOT attisdropped;

    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = table_oid AND contype = 'p' AND conkey = ARRAY[id_attribute]::SMALLINT[]
    ) THEN
        object_name := 'parrot_' || substr(md5(schema_name || '.' || table_name || ':pk'), 1, 16);
        EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I PRIMARY KEY (chatbot_id)', table_ref, object_name);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_constraint
        WHERE conrelid = table_oid AND contype = 'u' AND conkey = ARRAY[name_attribute]::SMALLINT[]
    ) THEN
        object_name := 'parrot_' || substr(md5(schema_name || '.' || table_name || ':name'), 1, 16);
        EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I UNIQUE (name)', table_ref, object_name);
    END IF;

    FOREACH constraint_expression IN ARRAY ARRAY[
        'tool_threshold >= 0 AND tool_threshold <= 1',
        'operation_mode IN (''conversational'', ''agentic'', ''adaptive'')',
        'context_search_limit > 0',
        'context_score_threshold >= 0 AND context_score_threshold <= 1',
        'memory_type IN (''memory'', ''file'', ''redis'')',
        'max_context_turns > 0'
    ] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_catalog.pg_constraint
            WHERE conrelid = table_oid
              AND contype = 'c'
              AND conname = 'parrot_' || substr(md5(schema_name || '.' || table_name || ':' || constraint_expression), 1, 16)
        ) THEN
            EXECUTE format(
                'ALTER TABLE %s ADD CONSTRAINT %I CHECK (%s)',
                table_ref,
                'parrot_' || substr(md5(schema_name || '.' || table_name || ':' || constraint_expression), 1, 16),
                constraint_expression
            );
        END IF;
    END LOOP;

    FOREACH object_name IN ARRAY ARRAY[
        'name', 'enabled', 'operation_mode', 'tools_enabled', 'use_vector', 'created_at', 'llm'
    ] LOOP
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %s (%I)',
            'parrot_' || substr(md5(schema_name || '.' || table_name || ':idx:' || object_name), 1, 16),
            table_ref,
            object_name
        );
    END LOOP;
    FOREACH object_name IN ARRAY ARRAY[
        'tools', 'permissions', 'model_config', 'reranker_config', 'parent_searcher_config'
    ] LOOP
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %s USING GIN (%I)',
            'parrot_' || substr(md5(schema_name || '.' || table_name || ':gin:' || object_name), 1, 16),
            table_ref,
            object_name
        );
    END LOOP;

    object_name := 'parrot_' || substr(md5(schema_name || '.' || table_name || ':updated_at'), 1, 16);
    EXECUTE format(
        'CREATE OR REPLACE FUNCTION %I.%I() RETURNS TRIGGER LANGUAGE plpgsql AS $function$ '
        'BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $function$',
        schema_name,
        object_name
    );
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_trigger
        WHERE tgrelid = table_oid AND tgname = object_name AND NOT tgisinternal
    ) THEN
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE ON %s FOR EACH ROW EXECUTE FUNCTION %I.%I()',
            object_name,
            table_ref,
            schema_name,
            object_name
        );
    END IF;
END;
$baseline$;
