-- Recreate navigator.ai_bots (BotModel) from scratch.
--
-- WARNING: DROP TABLE ... CASCADE destroys all existing bot rows and any
-- dependent objects. Remove CASCADE if you'd rather have it fail when
-- dependents exist. This DDL reflects the CURRENT BotModel field set
-- (packages/ai-parrot-server/src/parrot/handlers/models/bots.py), including
-- the legacy LLM-tuning columns that are still hydrated at load time.

-- Drop existing table first (CASCADE removes dependent objects/constraints)
DROP TABLE IF EXISTS navigator.ai_bots CASCADE;

-- Recreate the BotModel table
CREATE TABLE navigator.ai_bots (
    -- Primary key
    chatbot_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Basic bot information
    name VARCHAR NOT NULL,
    description VARCHAR,
    avatar TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    timezone VARCHAR(75) DEFAULT 'UTC',

    -- Bot personality and behavior
    role VARCHAR DEFAULT 'AI Assistant',
    goal VARCHAR NOT NULL DEFAULT 'Help users accomplish their tasks effectively.',
    backstory VARCHAR NOT NULL DEFAULT 'I am an AI assistant created to help users with various tasks.',
    rationale VARCHAR NOT NULL DEFAULT 'I maintain a professional tone and provide accurate, helpful information.',
    capabilities VARCHAR DEFAULT 'I can engage in conversation, answer questions, and use tools when needed.',

    -- Prompt configuration
    system_prompt_template TEXT,
    human_prompt_template VARCHAR,
    pre_instructions JSONB DEFAULT '[]'::JSONB,
    prompt_config JSONB NOT NULL DEFAULT '{}'::JSONB,

    -- LLM configuration (canonical home for tuning is model_config JSONB)
    llm VARCHAR DEFAULT 'google',
    model_config JSONB DEFAULT '{}'::JSONB,

    -- Legacy LLM-tuning columns (schema drift; folded into model_config /
    -- vector_store_config at hydration. Drop via
    -- sdd/migrations/FEAT-fold-legacy-llm-columns.sql once backfilled).
    model_name VARCHAR,
    temperature FLOAT,
    max_tokens INTEGER,
    top_k INTEGER,
    top_p FLOAT,
    embedding_model JSONB,

    -- Tool and agent configuration
    tools_enabled BOOLEAN DEFAULT TRUE,
    auto_tool_detection BOOLEAN DEFAULT TRUE,
    tool_threshold FLOAT DEFAULT 0.7,
    tools JSONB DEFAULT '[]'::JSONB,
    operation_mode VARCHAR DEFAULT 'adaptive'
        CHECK (operation_mode IN ('conversational', 'agentic', 'adaptive')),

    -- Knowledge base
    use_kb BOOLEAN DEFAULT FALSE,
    kb JSONB DEFAULT '[]'::JSONB,
    custom_kbs JSONB,

    -- Vector store and retrieval configuration
    use_vector BOOLEAN DEFAULT FALSE,
    vector_store_config JSONB DEFAULT '{}'::JSONB,
    reranker_config JSONB DEFAULT '{}'::JSONB,
    parent_searcher_config JSONB DEFAULT '{}'::JSONB,
    context_search_limit INTEGER DEFAULT 10,
    context_score_threshold FLOAT DEFAULT 0.7,

    -- Memory and conversation configuration
    memory_type VARCHAR DEFAULT 'memory'
        CHECK (memory_type IN ('memory', 'file', 'redis')),
    memory_config JSONB DEFAULT '{}'::JSONB,
    max_context_turns INTEGER DEFAULT 5,
    use_conversation_history BOOLEAN DEFAULT TRUE,

    -- Advanced: bot class
    bot_class VARCHAR DEFAULT 'BasicBot',

    -- Security and permissions
    permissions JSONB DEFAULT '{}'::JSONB,

    -- Metadata
    language VARCHAR DEFAULT 'en',
    disclaimer TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by INTEGER,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_ai_bots_name ON navigator.ai_bots(name);
CREATE INDEX IF NOT EXISTS idx_ai_bots_enabled ON navigator.ai_bots(enabled);
CREATE INDEX IF NOT EXISTS idx_ai_bots_operation_mode ON navigator.ai_bots(operation_mode);
CREATE INDEX IF NOT EXISTS idx_ai_bots_tools_enabled ON navigator.ai_bots(tools_enabled);

-- Unique constraint on name
ALTER TABLE navigator.ai_bots
    ADD CONSTRAINT unq_navigator_ai_bots_name UNIQUE (name);
