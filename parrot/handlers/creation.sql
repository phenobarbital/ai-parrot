-- Drop existing table if it exists (uncomment if needed)
DROP TABLE IF EXISTS navigator.ai_bots CASCADE;

-- Create the unified AI bots table
CREATE TABLE IF NOT EXISTS navigator.ai_bots (
    -- Primary key
    chatbot_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Basic bot information
    name VARCHAR NOT NULL,
    description TEXT,
    avatar TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    timezone VARCHAR(75) DEFAULT 'UTC',

    -- Bot personality and behavior
    role VARCHAR DEFAULT 'AI Assistant',
    goal TEXT NOT NULL DEFAULT 'Help users accomplish their tasks effectively.',
    backstory TEXT NOT NULL DEFAULT 'I am an AI assistant created to help users with various tasks.',
    rationale TEXT NOT NULL DEFAULT 'I maintain a professional tone and provide accurate, helpful information.',
    capabilities TEXT DEFAULT 'I can engage in conversation, answer questions, and use tools when needed.',

    -- Prompt configuration
    system_prompt_template TEXT,
    human_prompt_template TEXT,
    pre_instructions JSONB DEFAULT '[]'::JSONB,

    -- LLM configuration
    llm VARCHAR DEFAULT 'google',
    model_name VARCHAR DEFAULT 'gemini-2.0-flash-001',
    temperature FLOAT DEFAULT 0.1 CHECK (temperature >= 0 AND temperature <= 2),
    max_tokens INTEGER DEFAULT 1024 CHECK (max_tokens > 0),
    top_k INTEGER DEFAULT 41 CHECK (top_k > 0),
    top_p FLOAT DEFAULT 0.9 CHECK (top_p >= 0 AND top_p <= 1),
    model_config JSONB DEFAULT '{}'::JSONB,

    -- Tool and agent configuration
    tools_enabled BOOLEAN DEFAULT TRUE,
    auto_tool_detection BOOLEAN DEFAULT TRUE,
    tool_threshold FLOAT DEFAULT 0.7 CHECK (tool_threshold >= 0 AND tool_threshold <= 1),
    tools JSONB DEFAULT '[]'::JSONB,
    operation_mode VARCHAR DEFAULT 'adaptive' CHECK (operation_mode IN ('conversational', 'agentic', 'adaptive')),

    -- Vector store and retrieval configuration
    use_vector BOOLEAN DEFAULT FALSE,
    vector_store_config JSONB DEFAULT '{}'::JSONB,
    embedding_model JSONB DEFAULT '{"model_name": "sentence-transformers/all-MiniLM-L12-v2", "model_type": "huggingface"}'::JSONB,
    context_search_limit INTEGER DEFAULT 10 CHECK (context_search_limit > 0),
    context_score_threshold FLOAT DEFAULT 0.7 CHECK (context_score_threshold >= 0 AND context_score_threshold <= 1),

    -- Memory and conversation configuration
    memory_type VARCHAR DEFAULT 'memory' CHECK (memory_type IN ('memory', 'file', 'redis')),
    memory_config JSONB DEFAULT '{}'::JSONB,
    max_context_turns INTEGER DEFAULT 5 CHECK (max_context_turns > 0),
    use_conversation_history BOOLEAN DEFAULT TRUE,

    -- Security and permissions
    permissions JSONB DEFAULT '{}'::JSONB,

    -- Metadata
    language VARCHAR(10) DEFAULT 'en',
    disclaimer TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by INTEGER,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_ai_bots_name ON navigator.ai_bots(name);
CREATE INDEX IF NOT EXISTS idx_ai_bots_enabled ON navigator.ai_bots(enabled);
CREATE INDEX IF NOT EXISTS idx_ai_bots_operation_mode ON navigator.ai_bots(operation_mode);
CREATE INDEX IF NOT EXISTS idx_ai_bots_tools_enabled ON navigator.ai_bots(tools_enabled);
CREATE INDEX IF NOT EXISTS idx_ai_bots_use_vector ON navigator.ai_bots(use_vector);
CREATE INDEX IF NOT EXISTS idx_ai_bots_created_at ON navigator.ai_bots(created_at);
CREATE INDEX IF NOT EXISTS idx_ai_bots_llm ON navigator.ai_bots(llm);

-- Create a GIN index for JSONB columns for efficient querying
CREATE INDEX IF NOT EXISTS idx_ai_bots_tools_gin ON navigator.ai_bots USING GIN (tools);
CREATE INDEX IF NOT EXISTS idx_ai_bots_permissions_gin ON navigator.ai_bots USING GIN (permissions);
CREATE INDEX IF NOT EXISTS idx_ai_bots_model_config_gin ON navigator.ai_bots USING GIN (model_config);

-- Unique constraint on name
ALTER TABLE navigator.ai_bots
ADD CONSTRAINT unq_navigator_ai_bots_name UNIQUE (name);

-- Add comments for documentation
COMMENT ON TABLE navigator.ai_bots IS 'Unified AI bots table supporting both conversational and agentic capabilities';
COMMENT ON COLUMN navigator.ai_bots.chatbot_id IS 'Primary key UUID for the bot';
COMMENT ON COLUMN navigator.ai_bots.name IS 'Unique name identifier for the bot';
COMMENT ON COLUMN navigator.ai_bots.operation_mode IS 'Bot operation mode: conversational, agentic, or adaptive';
COMMENT ON COLUMN navigator.ai_bots.tools_enabled IS 'Whether the bot can use tools';
COMMENT ON COLUMN navigator.ai_bots.auto_tool_detection IS 'Whether the bot automatically detects when to use tools';
COMMENT ON COLUMN navigator.ai_bots.tool_threshold IS 'Confidence threshold for automatic tool usage (0-1)';
COMMENT ON COLUMN navigator.ai_bots.tools IS 'JSON array of available tool names';
COMMENT ON COLUMN navigator.ai_bots.use_vector IS 'Whether the bot uses vector store for context retrieval';
COMMENT ON COLUMN navigator.ai_bots.vector_store_config IS 'JSON configuration for vector store connection';
COMMENT ON COLUMN navigator.ai_bots.memory_type IS 'Type of conversation memory: memory, file, or redis';
COMMENT ON COLUMN navigator.ai_bots.pre_instructions IS 'JSON array of pre-instructions for the bot';
COMMENT ON COLUMN navigator.ai_bots.permissions IS 'JSON object defining bot access permissions';

-- Create a function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_ai_bots_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger to automatically update updated_at
CREATE TRIGGER trigger_ai_bots_updated_at
    BEFORE UPDATE ON navigator.ai_bots
    FOR EACH ROW
    EXECUTE FUNCTION update_ai_bots_updated_at();

-- Insert some example configurations
INSERT INTO navigator.ai_bots (
    name, description, role, goal, backstory, capabilities,
    tools_enabled, auto_tool_detection, tools, operation_mode, tool_threshold
) VALUES
(
    'ResearchBot',
    'AI assistant specialized in research and information gathering',
    'Research Assistant',
    'Help users find and analyze information from various sources',
    'I am a research-focused AI assistant trained to help users discover, analyze, and synthesize information.',
    'I can search the web, analyze documents, perform calculations, and help with research tasks',
    TRUE,
    TRUE,
    '["DuckDuckGoSearchTool", "MathTool", "PDFAnalysisTool"]'::JSONB,
    'adaptive',
    0.5
),
(
    'ChatBot',
    'Friendly conversational AI assistant',
    'Conversational Assistant',
    'Engage in helpful and friendly conversations',
    'I am a friendly AI assistant designed to have natural conversations and help with general questions.',
    'I can chat, answer questions, and provide information on a wide range of topics',
    FALSE,
    FALSE,
    '[]'::JSONB,
    'conversational',
    0.7
),
(
    'DataBot',
    'AI assistant specialized in data analysis and visualization',
    'Data Analyst',
    'Help users analyze and visualize data effectively',
    'I am a data-focused AI assistant with expertise in statistical analysis and data visualization.',
    'I can analyze datasets, create visualizations, perform statistical calculations, and help interpret data',
    TRUE,
    TRUE,
    '["MathTool", "DataAnalysisTool", "PlottingTool"]'::JSONB,
    'adaptive',
    0.3
) ON CONFLICT (name) DO NOTHING;

-- Create views for easier querying
CREATE OR REPLACE VIEW navigator.vw_active_bots AS
SELECT
    chatbot_id,
    name,
    description,
    role,
    operation_mode,
    tools_enabled,
    use_vector,
    llm,
    model_name,
    created_at,
    updated_at
FROM navigator.ai_bots
WHERE enabled = TRUE;

CREATE OR REPLACE VIEW navigator.vw_tool_enabled_bots AS
SELECT
    chatbot_id,
    name,
    description,
    tools,
    tool_threshold,
    auto_tool_detection,
    operation_mode
FROM navigator.ai_bots
WHERE enabled = TRUE AND tools_enabled = TRUE;

-- Grant appropriate permissions (adjust as needed for your setup)
-- GRANT SELECT, INSERT, UPDATE, DELETE ON navigator.ai_bots TO your_app_user;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA navigator TO your_app_user;
