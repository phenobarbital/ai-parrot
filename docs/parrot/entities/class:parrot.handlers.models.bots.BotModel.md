---
type: Wiki Entity
title: BotModel
id: class:parrot.handlers.models.bots.BotModel
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Unified Bot Model combining chatbot and agent functionality.
---

# BotModel

Defined in [`parrot.handlers.models.bots`](../summaries/mod:parrot.handlers.models.bots.md).

```python
class BotModel(Model)
```

Unified Bot Model combining chatbot and agent functionality.

This model represents any AI bot that can operate in conversational mode,
agentic mode, or adaptive mode based on the question content.

SQL Table Creation:

CREATE TABLE IF NOT EXISTS navigator.ai_bots (
    chatbot_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR NOT NULL,
    description VARCHAR,
    avatar TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    timezone VARCHAR DEFAULT 'UTC',

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

    -- LLM configuration
    --   ``model_config`` (JSONB) is the canonical home for all LLM
    --   tuning. Recognized keys: ``model`` / ``model_name``,
    --   ``temperature``, ``max_tokens``, ``top_k``, ``top_p``, plus
    --   any provider-specific keys.
    llm VARCHAR DEFAULT 'google',
    model_config JSONB DEFAULT '{}'::JSONB,

    -- Tool and agent configuration
    tools_enabled BOOLEAN DEFAULT TRUE,
    auto_tool_detection BOOLEAN DEFAULT TRUE,
    tool_threshold FLOAT DEFAULT 0.7,
    available_tools JSONB DEFAULT '[]'::JSONB,
    operation_mode VARCHAR DEFAULT 'adaptive' CHECK (operation_mode IN ('conversational', 'agentic', 'adaptive')),

    -- Vector store and retrieval configuration
    --   The embedding model lives at vector_store_config['embedding_model']
    --   (single source of truth — see migration
    --   FEAT-fold-embedding-model-into-vector-store-config.sql).
    use_vector_context BOOLEAN DEFAULT FALSE,
    vector_store_config JSONB DEFAULT '{}'::JSONB,
    reranker_config        JSONB DEFAULT '{}'::JSONB,
    parent_searcher_config JSONB DEFAULT '{}'::JSONB,
    context_search_limit INTEGER DEFAULT 10,
    context_score_threshold FLOAT DEFAULT 0.7,

    -- Memory and conversation configuration
    memory_type VARCHAR DEFAULT 'memory' CHECK (memory_type IN ('memory', 'file', 'redis')),
    memory_config JSONB DEFAULT '{}'::JSONB,
    max_context_turns INTEGER DEFAULT 5,
    use_conversation_history BOOLEAN DEFAULT TRUE,

    -- Security and permissions
    permissions JSONB DEFAULT '{}'::JSONB,

    --- knowledge base:
    use_kb BOOLEAN DEFAULT FALSE,
    kb JSONB DEFAULT '[]'::JSONB,

    -- Metadata
    language VARCHAR DEFAULT 'en',
    disclaimer TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by INTEGER,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for better performance
CREATE INDEX IF NOT EXISTS idx_ai_bots_name ON navigator.ai_bots(name);
CREATE INDEX IF NOT EXISTS idx_ai_bots_enabled ON navigator.ai_bots(enabled);
CREATE INDEX IF NOT EXISTS idx_ai_bots_operation_mode ON navigator.ai_bots(operation_mode);
CREATE INDEX IF NOT EXISTS idx_ai_bots_tools_enabled ON navigator.ai_bots(tools_enabled);

-- Unique constraint on name
ALTER TABLE navigator.ai_bots
ADD CONSTRAINT unq_navigator_ai_bots_name UNIQUE (name);

## Methods

- `def to_bot_config(self) -> dict` — Convert model instance to bot configuration dictionary.
- `def is_agent_enabled(self) -> bool` — Check if this bot has agent capabilities enabled.
- `def get_available_tool_names(self) -> List[str]` — Get list of available tool names.
- `def add_tool(self, tool_name: str) -> None` — Add a tool to the available tools list.
- `def remove_tool(self, tool_name: str) -> bool` — Remove a tool from the available tools list.
- `def enable_vector_store(self, config: dict) -> None` — Enable vector store with given configuration.
- `def disable_vector_store(self) -> None` — Disable vector store.
