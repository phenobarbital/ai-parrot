-- ============================================================
-- Homologate navigator.ai_bots with parrot.models.bots.BotModel
-- ============================================================
-- Table  : navigator.ai_bots
-- Purpose:
--   BotModel has Meta.strict = True, so asyncdb SELECTs every declared
--   field by name. Any column the model declares but the table lacks
--   fails EVERY bot load with, e.g.:
--
--     Error on get ai_bots: Error: Model GET over navigator.ai_bots:
--     column "toolkit_config" does not exist
--
--   Environments created from an older creation.sql drifted from the
--   model as columns were added feature by feature (prompt_config,
--   toolkit_config, mcp_servers, the knowledge-base trio, bot_class).
--   This migration adds every one of them in a single idempotent pass,
--   so no environment can be short a column again.
--
-- Additive only: it never drops anything. The columns the model no
-- longer declares are removed by their own fold migrations:
--   model_name/temperature/max_tokens/top_k/top_p
--       -> FEAT-fold-legacy-llm-columns.sql
--   embedding_model
--       -> FEAT-fold-embedding-model-into-vector-store-config.sql
--
-- Safe   : additive, idempotent, no data loss. Safe to re-run anywhere.
-- Status : pending
-- ============================================================

BEGIN;

-- Basic bot information
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS avatar                 TEXT;
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS timezone               VARCHAR(75) DEFAULT 'UTC';

-- Prompt configuration
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS prompt_config          JSONB NOT NULL DEFAULT '{}'::JSONB;

-- LLM configuration (canonical home for every tuning key)
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS model_config           JSONB DEFAULT '{}'::JSONB;

-- Tool and agent configuration (FEAT-593)
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS toolkit_config         JSONB DEFAULT '{}'::JSONB;
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS mcp_servers            JSONB DEFAULT '[]'::JSONB;

-- Knowledge base
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS use_kb                 BOOLEAN DEFAULT FALSE;
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS kb                     JSONB;
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS custom_kbs             JSONB;

-- Vector store and retrieval configuration (FEAT-133)
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS reranker_config        JSONB DEFAULT '{}'::JSONB;
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS parent_searcher_config JSONB DEFAULT '{}'::JSONB;

-- Advanced: bot class
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS bot_class              VARCHAR;

-- Security and permissions
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS permissions            JSONB DEFAULT '{}'::JSONB;

-- Metadata
ALTER TABLE navigator.ai_bots
    ADD COLUMN IF NOT EXISTS disclaimer             TEXT;

COMMENT ON COLUMN navigator.ai_bots.prompt_config  IS 'Declarative prompt-layer config: {preset, remove[], add[], customize{}}';
COMMENT ON COLUMN navigator.ai_bots.toolkit_config IS 'FEAT-593 — per-toolkit config {slug: ToolkitSpec}; secrets in vault';
COMMENT ON COLUMN navigator.ai_bots.mcp_servers    IS 'FEAT-593 — agent-level MCP servers; auth/headers/env in vault';

COMMIT;

-- ============================================================
-- Verify (every row must come back; 44 columns expected)
-- ============================================================
-- SELECT column_name FROM information_schema.columns
--  WHERE table_schema = 'navigator' AND table_name = 'ai_bots'
--  ORDER BY column_name;

-- ============================================================
-- Rollback
-- ============================================================
-- Not provided on purpose: dropping any of these columns puts the table
-- back into the state where every BotModel load fails.
