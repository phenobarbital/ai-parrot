-- Per-user bot definitions.
-- mcp_config and tools_config are stored as AES-GCM ciphertext (base64) because
-- they may carry credentials (api_keys, OAuth client_secret, tool args).
-- Encryption is performed transparently by parrot.handlers.models.users_bots.UserBotModel
-- using the navigator-session vault keys (same scheme as user_credentials).

CREATE TABLE IF NOT EXISTS navigator.users_bots (
    -- Composite identity. user_id references the navigator-auth users
    -- table (auth.users.user_id) so deleting an account also reaps every
    -- private bot it owns (and the encrypted credential blobs on those
    -- rows). The DELETE CASCADE is REQUIRED for credential hygiene — a
    -- deleted user must not leave readable encrypted secrets behind.
    chatbot_id     UUID NOT NULL DEFAULT uuid_generate_v4(),
    user_id        INTEGER NOT NULL
                   REFERENCES auth.users(user_id) ON DELETE CASCADE,

    -- Basic bot information
    name           VARCHAR NOT NULL,
    description    TEXT,
    avatar         TEXT,
    enabled        BOOLEAN NOT NULL DEFAULT TRUE,
    timezone       VARCHAR(75) DEFAULT 'UTC',

    -- Personality
    role           VARCHAR DEFAULT 'AI Assistant',
    goal           TEXT NOT NULL DEFAULT 'Help users accomplish their tasks effectively.',
    backstory      TEXT NOT NULL DEFAULT 'I am an AI assistant created to help users with various tasks.',
    rationale      TEXT NOT NULL DEFAULT 'I maintain a professional tone and provide accurate, helpful information.',
    capabilities   TEXT DEFAULT 'I can engage in conversation, answer questions, and use tools when needed.',

    -- Prompt configuration (PromptBuilder)
    prompt_config           JSONB NOT NULL DEFAULT '{}'::JSONB,
    system_prompt_template  TEXT,
    human_prompt_template   TEXT,
    pre_instructions        JSONB DEFAULT '[]'::JSONB,

    -- LLM configuration
    llm            VARCHAR NOT NULL DEFAULT 'google',
    model_name     VARCHAR NOT NULL DEFAULT 'gemini-3.1-flash-lite-preview',
    temperature    FLOAT DEFAULT 0.1 CHECK (temperature >= 0 AND temperature <= 2),
    max_tokens     INTEGER DEFAULT 4096 CHECK (max_tokens > 0),
    top_k          INTEGER DEFAULT 41 CHECK (top_k > 0),
    top_p          FLOAT DEFAULT 0.9 CHECK (top_p >= 0 AND top_p <= 1),
    model_config   JSONB DEFAULT '{}'::JSONB,

    -- Vector store + uploaded documents (S3 paths)
    use_vector              BOOLEAN DEFAULT FALSE,
    vector_config           JSONB DEFAULT '{}'::JSONB,
    embedding_model         JSONB DEFAULT '{"model_name": "sentence-transformers/all-mpnet-base-v2", "model_type": "huggingface"}'::JSONB,
    documents               JSONB DEFAULT '[]'::JSONB,
    context_search_limit    INTEGER DEFAULT 10 CHECK (context_search_limit > 0),
    context_score_threshold FLOAT DEFAULT 0.61 CHECK (context_score_threshold >= 0 AND context_score_threshold <= 1),

    -- MCP & tools — ENCRYPTED at rest (AES-GCM, base64 ciphertext)
    mcp_config     TEXT,
    tools_config   TEXT,
    tools_enabled  BOOLEAN DEFAULT TRUE,
    auto_tool_detection BOOLEAN DEFAULT TRUE,
    tool_threshold FLOAT DEFAULT 0.7 CHECK (tool_threshold >= 0 AND tool_threshold <= 1),
    operation_mode VARCHAR DEFAULT 'adaptive' CHECK (operation_mode IN ('conversational', 'agentic', 'adaptive')),

    -- Memory and conversation
    memory_type    VARCHAR DEFAULT 'memory' CHECK (memory_type IN ('memory', 'file', 'redis')),
    memory_config  JSONB DEFAULT '{}'::JSONB,
    max_context_turns INTEGER DEFAULT 5 CHECK (max_context_turns > 0),
    use_conversation_history BOOLEAN DEFAULT TRUE,

    -- Security and permissions
    permissions    JSONB DEFAULT '{}'::JSONB,

    -- Metadata
    language       VARCHAR(10) DEFAULT 'en',
    disclaimer     TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (user_id, chatbot_id),
    CONSTRAINT unq_users_bots_user_name UNIQUE (user_id, name)
);

CREATE INDEX IF NOT EXISTS idx_users_bots_user_id ON navigator.users_bots(user_id);
CREATE INDEX IF NOT EXISTS idx_users_bots_enabled ON navigator.users_bots(enabled);
CREATE INDEX IF NOT EXISTS idx_users_bots_chatbot_id ON navigator.users_bots(chatbot_id);

CREATE OR REPLACE FUNCTION update_users_bots_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS trigger_users_bots_updated_at ON navigator.users_bots;
CREATE TRIGGER trigger_users_bots_updated_at
    BEFORE UPDATE ON navigator.users_bots
    FOR EACH ROW
    EXECUTE FUNCTION update_users_bots_updated_at();

COMMENT ON TABLE  navigator.users_bots IS 'Per-user user-defined bots. mcp_config and tools_config are AES-GCM encrypted blobs (may carry credentials).';
COMMENT ON COLUMN navigator.users_bots.mcp_config   IS 'AES-GCM encrypted (base64) blob carrying MCP server configurations (may include credentials).';
COMMENT ON COLUMN navigator.users_bots.tools_config IS 'AES-GCM encrypted (base64) blob carrying tool configurations (may include credentials).';
COMMENT ON COLUMN navigator.users_bots.documents    IS 'JSON list of uploaded document descriptors {name, path, url, size, content_type, s3_key}.';
